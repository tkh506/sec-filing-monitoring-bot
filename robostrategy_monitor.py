"""Diffing + the scheduled check cycle for the RoboStrategy portfolio monitor.

The alert is always a three-section factual summary -- Portfolio Composition, % of NAV Changes,
Total NAV & NAV per Share -- with each section reporting "No Change" explicitly when nothing moved
in that category, rather than being omitted. This is a deliberate design (agreed with the user):
when a category has more than 2 changes, the section reports the count and names only the top 2 by
magnitude, to keep the message readable regardless of how much changed. All of this is deterministic,
computed from parsed numbers -- no AI involved in deciding what changed (see INTRODUCTION.md). The
optional "AI Take" button (wired in handlers/callbacks.py) only turns an already-computed factual
summary into readable prose on tap; it never decides what counts as a change.

`Holding.fair_value` is `float | None` and, in practice, always None: RoboStrategy removed the
per-holding dollar Fair Value column in a 2026-07 redesign (see robostrategy_client.py's module
docstring) and there's no reliable substitute source for it. Kept optional rather than dropped in
case a future redesign brings it back. `total_nav`/`nav_per_share` are also `float | None` but
*are* populated today -- they moved to a prose footnote sentence rather than disappearing.
"""
import json
import logging
from dataclasses import dataclass
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
_TOTAL_NAV_EPSILON = 0.5

# Above this count in a category, name only the top 2 by magnitude instead of listing everyone.
_SUMMARIZE_THRESHOLD = 2

_NOTE_TEXT = (
    "(% of NAV is share-of-total — a change in one holding's value shifts every holding's %, "
    "even ones whose own value didn't change.)"
)


@dataclass(frozen=True)
class PortfolioSummary:
    composition_text: str
    pct_change_text: str
    nav_text: str
    has_any_change: bool


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
    return RobostrategySnapshot(
        as_of=row["as_of"],
        nav_per_share=row["nav_per_share"],
        holdings=holdings,
        total_nav=row["total_nav"],
        nav_as_of=row["nav_as_of"],
    )


def _save_snapshot(snapshot: RobostrategySnapshot) -> None:
    db.save_robostrategy_snapshot(
        snapshot.as_of,
        snapshot.nav_per_share,
        json.dumps(_holdings_to_dicts(snapshot.holdings)),
        snapshot.total_nav,
        snapshot.nav_as_of,
    )


def _added_and_removed(
    previous: RobostrategySnapshot, current: RobostrategySnapshot
) -> tuple[list[Holding], list[Holding]]:
    prev_by_name = {h.name: h for h in previous.holdings}
    curr_by_name = {h.name: h for h in current.holdings}
    added = [h for name, h in curr_by_name.items() if name not in prev_by_name]
    removed = [h for name, h in prev_by_name.items() if name not in curr_by_name]
    return added, removed


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
        pct_changed = abs(curr_h.pct_nav - prev_h.pct_nav) > _PCT_EPSILON
        fair_value_changed = (
            prev_h.fair_value is not None
            and curr_h.fair_value is not None
            and abs(curr_h.fair_value - prev_h.fair_value) > _FAIR_VALUE_EPSILON
        )
        if pct_changed or fair_value_changed:
            changed.append((curr_h.name, prev_h, curr_h))
    return changed


def _format_composition_section(added: list[Holding], removed: list[Holding]) -> str:
    if not added and not removed:
        return "No Change"

    lines = []
    if added:
        if len(added) <= _SUMMARIZE_THRESHOLD:
            names = "; ".join(f"{h.name} ({h.pct_nav:.1f}% of NAV)" for h in added)
            lines.append(f"➕ Added: {names}")
        else:
            top = sorted(added, key=lambda h: h.pct_nav, reverse=True)[:2]
            examples = " and ".join(f"{h.name} ({h.pct_nav:.1f}% of NAV)" for h in top)
            lines.append(f"➕ {len(added)} companies added, including {examples}")

    if removed:
        if len(removed) <= _SUMMARIZE_THRESHOLD:
            names = "; ".join(f"{h.name} (was {h.pct_nav:.1f}% of NAV)" for h in removed)
            lines.append(f"➖ Removed: {names}")
        else:
            top = sorted(removed, key=lambda h: h.pct_nav, reverse=True)[:2]
            examples = " and ".join(f"{h.name} (was {h.pct_nav:.1f}% of NAV)" for h in top)
            lines.append(f"➖ {len(removed)} companies removed, including {examples}")

    return "\n".join(lines)


def _format_pct_change_section(changed: list[tuple[str, Holding, Holding]]) -> str:
    if not changed:
        return "No Change"

    if len(changed) <= _SUMMARIZE_THRESHOLD:
        return "\n".join(
            f"{name}: {prev_h.pct_nav:.1f}% → {curr_h.pct_nav:.1f}%" for name, prev_h, curr_h in changed
        )

    top = sorted(changed, key=lambda c: abs(c[2].pct_nav - c[1].pct_nav), reverse=True)[:2]
    examples = " and ".join(f"{name} ({prev_h.pct_nav:.1f}% → {curr_h.pct_nav:.1f}%)" for name, prev_h, curr_h in top)
    return f"{len(changed)} companies had % of NAV changes, including {examples}"


def _format_nav_section(previous: RobostrategySnapshot, current: RobostrategySnapshot) -> tuple[str, bool]:
    total_nav_changed = (
        previous.total_nav is not None
        and current.total_nav is not None
        and abs(current.total_nav - previous.total_nav) > _TOTAL_NAV_EPSILON
    )
    nav_per_share_changed = (
        previous.nav_per_share is not None
        and current.nav_per_share is not None
        and abs(current.nav_per_share - previous.nav_per_share) > _NAV_EPSILON
    )
    changed = total_nav_changed or nav_per_share_changed

    if changed:
        # Show both figures for context whenever either one moved, even if only one actually did.
        lines = []
        if previous.total_nav is not None and current.total_nav is not None:
            lines.append(f"Total NAV: ${previous.total_nav:,.0f} → ${current.total_nav:,.0f}")
        if previous.nav_per_share is not None and current.nav_per_share is not None:
            lines.append(f"NAV per share: ${previous.nav_per_share:.2f} → ${current.nav_per_share:.2f}")
        return "\n".join(lines), True

    parts = []
    if current.total_nav is not None:
        parts.append(f"Total NAV: ${current.total_nav:,.0f}")
    if current.nav_per_share is not None:
        parts.append(f"NAV per share: ${current.nav_per_share:.2f}")
    restated = ", ".join(parts)
    return (f"No Change. {restated}" if restated else "No Change"), False


def build_portfolio_summary(previous: RobostrategySnapshot, current: RobostrategySnapshot) -> PortfolioSummary:
    """Pure function: builds the three-section factual summary comparing two snapshots."""
    added, removed = _added_and_removed(previous, current)
    changed = _changed_holdings(previous, current)
    composition_text = _format_composition_section(added, removed)
    pct_change_text = _format_pct_change_section(changed)
    nav_text, nav_changed = _format_nav_section(previous, current)
    has_any_change = bool(added or removed or changed or nav_changed)
    return PortfolioSummary(
        composition_text=composition_text,
        pct_change_text=pct_change_text,
        nav_text=nav_text,
        has_any_change=has_any_change,
    )


def _format_message(current: RobostrategySnapshot, summary: PortfolioSummary) -> str:
    header = f"📊 <b>RoboStrategy Portfolio Update</b> — as of {current.as_of or 'unknown date'}"
    body = (
        f"<b>1) Portfolio Composition</b>\n{summary.composition_text}\n\n"
        f"<b>2) % of NAV Changes</b>\n{summary.pct_change_text}\n\n"
        f"<b>3) Total NAV &amp; NAV per Share</b>\n{summary.nav_text}"
    )
    show_note = summary.composition_text != "No Change" or summary.pct_change_text != "No Change"
    note = f"\n\n{_NOTE_TEXT}" if show_note else ""
    return f"{header}\n\n{body}{note}\n\n{PORTFOLIO_URL}"


def _build_diff_text(summary: PortfolioSummary) -> str:
    return (
        f"Portfolio Composition: {summary.composition_text}\n"
        f"% of NAV Changes: {summary.pct_change_text}\n"
        f"Total NAV & NAV per Share: {summary.nav_text}"
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
            summary = build_portfolio_summary(current, current)  # trivially all "No Change"
            message = _format_message(current, summary)
            for user_id in subscribers:
                await send_with_retry(bot, user_id, message, parse_mode="HTML")
        return

    summary = build_portfolio_summary(previous, current)

    if summary.has_any_change or is_midnight_run:
        message = _format_message(current, summary)
        if summary.has_any_change:
            diff_text = _build_diff_text(summary)
            for user_id in subscribers:
                summary_id = db.insert_robostrategy_pending_ai(diff_text)
                reply_markup = InlineKeyboardMarkup(
                    [[InlineKeyboardButton("🤖 AI Take", callback_data=f"rsai:{summary_id}")]]
                )
                await send_with_retry(bot, user_id, message, parse_mode="HTML", reply_markup=reply_markup)
        else:
            for user_id in subscribers:
                await send_with_retry(bot, user_id, message, parse_mode="HTML")

    _save_snapshot(current)
