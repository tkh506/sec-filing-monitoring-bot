"""Diffing + the scheduled check cycle for the RoboStrategy portfolio monitor.

All three tracked changes (company added/removed, fair value/% of NAV change, NAV per share
change) are deterministic diffs -- no AI involved here by design (see INTRODUCTION.md). The
optional "AI Take" button (wired in handlers/callbacks.py) only turns an already-computed factual
diff into readable prose on tap; it never decides what counts as a change.
"""
import json
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

import db
from robostrategy_client import (
    Holding,
    RobostrategySnapshot,
    fetch_portfolio_html,
    parse_portfolio,
)
from telegram_utils import send_with_retry

logger = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")
PORTFOLIO_URL = "https://robostrategy.co/portfolio"

_FAIR_VALUE_EPSILON = 0.005
_PCT_EPSILON = 0.05
_NAV_EPSILON = 0.001

_NOTE_TEXT = (
    "(% of NAV is share-of-total — one holding's fair-value move shifts every holding's %, "
    "even ones whose own fair value didn't change.)"
)


def _now_et_hour() -> int:
    return datetime.now(ET).hour


def _holdings_to_dicts(holdings: tuple[Holding, ...]) -> list[dict]:
    return [
        {"name": h.name, "business": h.business, "fair_value": h.fair_value, "pct_nav": h.pct_nav}
        for h in holdings
    ]


def _load_previous_snapshot() -> RobostrategySnapshot | None:
    row = db.get_robostrategy_snapshot()
    if row is None:
        return None
    holdings = tuple(Holding(**h) for h in json.loads(row["holdings_json"]))
    return RobostrategySnapshot(as_of=row["as_of"], nav_per_share=row["nav_per_share"], holdings=holdings)


def _save_snapshot(snapshot: RobostrategySnapshot) -> None:
    db.save_robostrategy_snapshot(
        snapshot.as_of, snapshot.nav_per_share, json.dumps(_holdings_to_dicts(snapshot.holdings))
    )


def _changed_holdings(
    previous: RobostrategySnapshot, current: RobostrategySnapshot
) -> list[tuple[str, Holding, Holding]]:
    """Holdings present in both snapshots whose fair value or % of NAV moved."""
    prev_by_name = {h.name: h for h in previous.holdings}
    changed = []
    for curr_h in current.holdings:
        prev_h = prev_by_name.get(curr_h.name)
        if prev_h is None:
            continue
        if (
            abs(curr_h.fair_value - prev_h.fair_value) > _FAIR_VALUE_EPSILON
            or abs(curr_h.pct_nav - prev_h.pct_nav) > _PCT_EPSILON
        ):
            changed.append((curr_h.name, prev_h, curr_h))
    return changed


def diff_snapshots(previous: RobostrategySnapshot, current: RobostrategySnapshot) -> list[str]:
    """Pure function: compares two snapshots, returns factual change-description lines (empty
    if nothing changed). Every line states a number from the data -- no interpretation."""
    lines: list[str] = []

    prev_names = {h.name for h in previous.holdings}
    curr_by_name = {h.name: h for h in current.holdings}

    for name, h in curr_by_name.items():
        if name not in prev_names:
            lines.append(f"➕ Added: {name} ({h.business}) — ${h.fair_value:,.0f} ({h.pct_nav:.1f}% of NAV)")

    curr_names = set(curr_by_name)
    for name in prev_names - curr_names:
        lines.append(f"➖ Removed: {name}")

    for name, prev_h, curr_h in _changed_holdings(previous, current):
        lines.append(
            f"{name}: ${prev_h.fair_value:,.0f} → ${curr_h.fair_value:,.0f}  "
            f"({prev_h.pct_nav:.1f}% → {curr_h.pct_nav:.1f}% of NAV)"
        )

    if (
        previous.nav_per_share is not None
        and current.nav_per_share is not None
        and abs(current.nav_per_share - previous.nav_per_share) > _NAV_EPSILON
    ):
        pct_change = (
            (current.nav_per_share - previous.nav_per_share) / previous.nav_per_share * 100
            if previous.nav_per_share
            else 0.0
        )
        sign = "+" if pct_change >= 0 else ""
        lines.append(
            f"NAV per share: ${previous.nav_per_share:.2f} → ${current.nav_per_share:.2f} "
            f"({sign}{pct_change:.1f}%)"
        )

    return lines


def _format_message(current: RobostrategySnapshot, change_lines: list[str], include_note: bool) -> str:
    header = f"📊 <b>RoboStrategy Portfolio Update</b> — as of {current.as_of or 'unknown date'}"
    body = "\n".join(change_lines)
    note = f"\n\n{_NOTE_TEXT}" if include_note else ""
    return f"{header}\n\n{body}{note}\n\n{PORTFOLIO_URL}"


def _format_heartbeat(current: RobostrategySnapshot) -> str:
    nav_text = f"${current.nav_per_share:.2f}" if current.nav_per_share is not None else "unknown"
    return (
        f"✅ No changes to the RoboStrategy portfolio today. "
        f"NAV per share: {nav_text} across {len(current.holdings)} holdings."
    )


async def run_robostrategy_check(bot, user_agent: str) -> None:
    subscribers = db.get_robostrategy_subscribers()
    if not subscribers:
        return

    try:
        page_html = await fetch_portfolio_html(user_agent)
        current = parse_portfolio(page_html)
    except Exception:
        logger.exception("RoboStrategy fetch/parse failed")
        warning = f"⚠️ Couldn't check the RoboStrategy portfolio page (parsing failed). Check manually: {PORTFOLIO_URL}"
        for user_id in subscribers:
            await send_with_retry(bot, user_id, warning)
        return

    previous = _load_previous_snapshot()
    is_midnight_run = _now_et_hour() == 0

    if previous is None:
        # First-ever check: establish the baseline only, no diff/backfill message -- consistent
        # with the SEC side's "first-watch never backfills" policy (handlers/actions.py:do_watch).
        _save_snapshot(current)
        if is_midnight_run:
            heartbeat = _format_heartbeat(current)
            for user_id in subscribers:
                await send_with_retry(bot, user_id, heartbeat)
        return

    change_lines = diff_snapshots(previous, current)

    if change_lines:
        include_note = bool(_changed_holdings(previous, current))
        message = _format_message(current, change_lines, include_note)
        diff_text = "\n".join(change_lines)
        for user_id in subscribers:
            summary_id = db.insert_robostrategy_pending_ai(diff_text)
            reply_markup = InlineKeyboardMarkup(
                [[InlineKeyboardButton("🤖 AI Take", callback_data=f"rsai:{summary_id}")]]
            )
            await send_with_retry(bot, user_id, message, parse_mode="HTML", reply_markup=reply_markup)
    elif is_midnight_run:
        heartbeat = _format_heartbeat(current)
        for user_id in subscribers:
            await send_with_retry(bot, user_id, heartbeat)

    _save_snapshot(current)
