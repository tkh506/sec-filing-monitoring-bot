"""Per-cycle EDGAR polling: dedupe by CIK, diff per subscriber, fan out alerts."""
import dataclasses
import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

import db
from classifier import classify_and_render
from edgar_client import EdgarFetchError, parse_recent_filings
from models import Filing
from telegram_utils import send_with_retry

logger = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")
MAX_BACKFILL = 10


def now_et() -> datetime:
    return datetime.now(ET)


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _filings_since(recent_filings: list[Filing], last_seen: str | None) -> list[Filing]:
    """Newest-first subset of filings strictly newer than `last_seen`."""
    if not recent_filings:
        return []
    if last_seen is None:
        # Defensive fallback only -- /watch sets a real baseline at subscribe
        # time, so this path shouldn't normally be hit.
        return recent_filings[:1]
    idx = next((i for i, f in enumerate(recent_filings) if f.accession_no == last_seen), None)
    if idx is None:
        # last_seen has rolled out of EDGAR's "recent" window (long downtime).
        # Cap the catch-up burst rather than flooding the user.
        logger.warning(
            "last_seen_accession_no %s not found in recent window; capping backfill at %d",
            last_seen,
            MAX_BACKFILL,
        )
        return recent_filings[:MAX_BACKFILL]
    return recent_filings[:idx]


async def send_filing_alert(bot, user_id: int, filing: Filing, edgar) -> None:
    """Classify + render a single filing and send it. Used by the poller's per-cycle fan-out and
    by the on-demand "latest filings" lookup (handlers/actions.py:do_show_recent)."""
    result, is_standardized = await classify_and_render(filing, edgar)

    # Always offer the AI button, even on a standardized alert -- it's on-demand (costs nothing
    # unless tapped), and the preset summary occasionally misses context a filer's own wording
    # would surface, so it's still worth having available.
    summary_id = db.insert_pending_summary(
        filing.ticker, filing.cik, filing.accession_no, filing.filing_index_url, filing.form
    )
    button_label = "🤖 Ask AI Anyway" if is_standardized else "🤖 Summarize with AI"
    reply_markup = InlineKeyboardMarkup(
        [[InlineKeyboardButton(button_label, callback_data=f"summarize:{summary_id}")]]
    )

    await send_with_retry(
        bot, user_id, result.text, parse_mode=result.parse_mode, reply_markup=reply_markup
    )


async def _send_no_new_filings(bot, user_id: int, ticker: str) -> None:
    text = f"✅ No new filings for {ticker} in the last 24h. Bot is running."
    await send_with_retry(bot, user_id, text)


async def run_check_cycle(frequency_hours: int, edgar, bot) -> None:
    rows = db.get_watchlist_rows_by_frequency(frequency_hours)
    if not rows:
        return

    by_cik: dict[str, list] = {}
    for row in rows:
        by_cik.setdefault(row.cik, []).append(row)

    is_midnight_run = now_et().hour == 0

    for cik, subscribers in by_cik.items():
        try:
            submissions = await edgar.get_submissions(cik)
        except EdgarFetchError:
            logger.warning("Failed to fetch submissions for CIK %s; skipping this cycle.", cik)
            continue

        recent_filings = parse_recent_filings(cik, submissions)

        for sub in subscribers:
            checked_at = now_utc_iso()
            try:
                new_filings = _filings_since(recent_filings, sub.last_seen_accession_no)

                if new_filings:
                    for filing in reversed(new_filings):
                        filing_for_user = dataclasses.replace(filing, ticker=sub.ticker)
                        await send_filing_alert(bot, sub.user_id, filing_for_user, edgar)
                    newest = new_filings[0]
                    db.update_watchlist_checkpoint(sub.id, newest.accession_no, checked_at)
                else:
                    if is_midnight_run:
                        await _send_no_new_filings(bot, sub.user_id, sub.ticker)
                    db.update_watchlist_checkpoint(sub.id, sub.last_seen_accession_no, checked_at)
            except Exception:
                logger.exception(
                    "Unexpected error processing watchlist entry %s (user=%s, ticker=%s)",
                    sub.id,
                    sub.user_id,
                    sub.ticker,
                )
                continue
