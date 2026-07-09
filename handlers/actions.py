"""Business logic shared between slash-command handlers and inline-button callbacks.

Keeping this here means the two entry points (typing "/watch NVDA" vs. tapping
"Add Ticker" then typing "NVDA") never duplicate the watch/unwatch/frequency logic.
"""
import dataclasses
import logging
import re

from telegram.ext import ContextTypes

import db
from edgar_client import EdgarFetchError, parse_recent_filings
from handlers import menu
from poller import send_filing_alert

logger = logging.getLogger(__name__)

_TICKER_RE = re.compile(r"^[A-Z0-9.\-]{1,10}$")

RECENT_FILINGS_COUNT = 5


def get_edgar(context: ContextTypes.DEFAULT_TYPE):
    return context.application.bot_data["edgar"]


async def _resolve_cik(ticker: str, edgar) -> tuple[str, str] | str:
    """Returns (cik, company_name) on success, or an error message string on failure."""
    cached = db.get_cached_cik(ticker)
    if cached is not None:
        return cached["cik"], cached["company_name"]
    try:
        resolved = await edgar.resolve_ticker(ticker)
    except EdgarFetchError:
        return "SEC EDGAR lookup failed, try again shortly."
    if resolved is None:
        return f"Unknown ticker: {ticker}"
    cik, company_name = resolved
    db.upsert_cik(ticker, cik, company_name)
    return cik, company_name


async def do_watch(user_id: int, ticker_raw: str, edgar) -> tuple[str, str | None]:
    """Returns (reply_text, ticker_added). ticker_added is None if the watch failed."""
    ticker = ticker_raw.strip().upper()
    if not _TICKER_RE.match(ticker):
        return f"That doesn't look like a valid ticker symbol: {ticker_raw!r}. Try e.g. NVDA.", None

    if db.count_watchlist(user_id) >= db.MAX_WATCHLIST_PER_USER:
        return (
            f"You're already watching {db.MAX_WATCHLIST_PER_USER} tickers. "
            f"Unwatch one first from the menu.",
            None,
        )

    if db.get_watchlist_entry(user_id, ticker) is not None:
        return f"You're already watching {ticker}.", None

    resolved = await _resolve_cik(ticker, edgar)
    if isinstance(resolved, str):
        return resolved, None
    cik, company_name = resolved

    baseline_accession_no = None
    try:
        submissions = await edgar.get_submissions(cik)
        recent_filings = parse_recent_filings(cik, submissions)
        if recent_filings:
            baseline_accession_no = recent_filings[0].accession_no
    except EdgarFetchError:
        logger.warning("Could not fetch baseline submissions for %s (%s)", ticker, cik)

    db.add_watchlist_entry(
        user_id, ticker, cik, frequency_hours=6, last_seen_accession_no=baseline_accession_no
    )
    return (
        f"✅ Now watching {ticker} ({company_name or cik}).\n"
        f"Checking every 6h — tap below to change that.",
        ticker,
    )


async def do_unwatch(user_id: int, ticker: str) -> str:
    ticker = ticker.strip().upper()
    if db.remove_watchlist_entry(user_id, ticker):
        return f"🗑 Stopped watching {ticker}."
    return f"You weren't watching {ticker}."


async def do_set_frequency(user_id: int, ticker: str, hours: int) -> str:
    ticker = ticker.strip().upper()
    if db.set_frequency(user_id, ticker, hours):
        return f"⏱ {ticker} check frequency set to {hours}h."
    return f"You're not watching {ticker}."


async def do_show_recent(bot, user_id: int, ticker_raw: str, edgar) -> str | None:
    """Sends the N most recent filings for any ticker, rendered exactly like a real alert
    (standardized template, or generic + Summarize-with-AI button). Doesn't require the ticker
    to be on the watchlist -- this is a quick-reference / "check the bot works right now" lookup,
    independent of the scheduled poll cycle.

    Returns an error message string on failure, or None once filings were sent successfully.
    """
    ticker = ticker_raw.strip().upper()
    if not _TICKER_RE.match(ticker):
        return f"That doesn't look like a valid ticker symbol: {ticker_raw!r}. Try e.g. NVDA."

    resolved = await _resolve_cik(ticker, edgar)
    if isinstance(resolved, str):
        return resolved
    cik, _company_name = resolved

    try:
        submissions = await edgar.get_submissions(cik)
    except EdgarFetchError:
        return "SEC EDGAR lookup failed, try again shortly."

    recent_filings = parse_recent_filings(cik, submissions)[:RECENT_FILINGS_COUNT]
    if not recent_filings:
        return f"No filings found for {ticker}."

    await bot.send_message(chat_id=user_id, text=f"📰 Latest {len(recent_filings)} filing(s) for {ticker}:")
    for filing in reversed(recent_filings):  # oldest-first, same convention as real alerts
        filing_for_user = dataclasses.replace(filing, ticker=ticker)
        await send_filing_alert(bot, user_id, filing_for_user, edgar)
    await bot.send_message(chat_id=user_id, text="What next?", reply_markup=menu.main_menu(user_id))
    return None
