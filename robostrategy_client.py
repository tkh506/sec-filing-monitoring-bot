"""Fetch + parse RoboStrategy's public portfolio page (https://robostrategy.co/portfolio).

Unlike SEC EDGAR, this is a marketing website's own HTML with no schema guarantee -- there's no
regulator-mandated taxonomy behind it, just whatever markup RoboStrategy's Framer site happens to
emit today. Parsing is deliberately defensive: any structural surprise raises
RobostrategyParseError rather than silently returning wrong or partial data, so the caller can
alert "couldn't parse, check manually" instead of going quiet.

Validated live against the real page before this was written: the table is a sequence of
`data-framer-name="Portfolio Entry"` blocks, each with exactly 5 `<p>` cells in order --
Company Name, footnote markers (e.g. "(a)(b)(c)"), Nature of Business, Fair Value ($), % of Net
Assets. Framer duplicates the *entire* table in the HTML for a responsive-breakpoint variant (the
real page currently repeats it 4x) -- rather than hardcode a duplication factor, `_minimal_period`
detects the shortest repeating run of rows and keeps just one copy.
"""
import html
import re
from dataclasses import dataclass

import httpx

PORTFOLIO_URL = "https://robostrategy.co/portfolio"

_ENTRY_MARKER_RE = re.compile(r'data-framer-name="Portfolio Entry"')
_PARAGRAPH_RE = re.compile(r"<p[^>]*>([^<]*)</p>")
_FOOTNOTE_RE = re.compile(r"^(\([a-z0-9]+\))+$", re.IGNORECASE)
_FAIR_VALUE_RE = re.compile(r"\$?([\d,]+(?:\.\d+)?)")
_PCT_RE = re.compile(r"(-?[\d.]+)%")
_AS_OF_RE = re.compile(r"As of ([A-Za-z]+ \d{1,2}, \d{4}) monthly NAV")
_ENTRY_WINDOW_CHARS = 3000
_NAV_PER_SHARE_WINDOW_CHARS = 1500


class RobostrategyParseError(Exception):
    pass


@dataclass(frozen=True)
class Holding:
    name: str
    business: str
    fair_value: float
    pct_nav: float


@dataclass(frozen=True)
class RobostrategySnapshot:
    as_of: str | None
    nav_per_share: float | None
    holdings: tuple[Holding, ...]


async def fetch_portfolio_html(user_agent: str) -> str:
    headers = {"User-Agent": user_agent}
    async with httpx.AsyncClient(headers=headers, timeout=20.0, follow_redirects=True) as client:
        resp = await client.get(PORTFOLIO_URL)
        resp.raise_for_status()
        return resp.text


def _minimal_period(rows: list[tuple]) -> int:
    """Shortest P such that rows == rows[:P] repeated -- avoids hardcoding a duplication factor
    that could change if RoboStrategy's site adds/removes a responsive breakpoint variant."""
    n = len(rows)
    for p in range(1, n + 1):
        if n % p == 0 and all(rows[i] == rows[i % p] for i in range(n)):
            return p
    return n


def _parse_holdings(page_html: str) -> list[Holding]:
    positions = [m.start() for m in _ENTRY_MARKER_RE.finditer(page_html)]
    if not positions:
        raise RobostrategyParseError("No portfolio entries found -- page structure may have changed.")

    raw_rows = []
    for i, pos in enumerate(positions):
        end = positions[i + 1] if i + 1 < len(positions) else pos + _ENTRY_WINDOW_CHARS
        chunk = page_html[pos : min(end, pos + _ENTRY_WINDOW_CHARS)]
        cells_seen = _PARAGRAPH_RE.findall(chunk)
        # A row is [name, footnote?, business, fair_value, pct] -- footnote is optional, so the
        # real row length depends on content (does cells_seen[1] look like a footnote marker?).
        # Deciding this BEFORE truncating matters: a fixed-size slice can pull in bleed from
        # trailing page content (e.g. the "Total Investments" summary row) whenever a
        # footnote-less row happens to be the last entry on the page.
        row_len = 5 if len(cells_seen) > 1 and _FOOTNOTE_RE.match(cells_seen[1]) else 4
        raw_rows.append(tuple(cells_seen[:row_len]))

    period = _minimal_period(raw_rows)
    unique_rows = raw_rows[:period]

    holdings = []
    for cells in unique_rows:
        if len(cells) == 5:
            name, business, fair_value_raw, pct_raw = cells[0], cells[2], cells[3], cells[4]
        elif len(cells) == 4:
            name, business, fair_value_raw, pct_raw = cells[0], cells[1], cells[2], cells[3]
        else:
            raise RobostrategyParseError(f"Unexpected portfolio row shape: {cells!r}")

        fv_match = _FAIR_VALUE_RE.search(fair_value_raw)
        pct_match = _PCT_RE.search(pct_raw)
        if not fv_match or not pct_match:
            raise RobostrategyParseError(f"Could not parse fair value/pct from row: {cells!r}")

        holdings.append(
            Holding(
                name=html.unescape(name.strip()),
                business=html.unescape(business.strip()),
                fair_value=float(fv_match.group(1).replace(",", "")),
                pct_nav=float(pct_match.group(1)),
            )
        )
    return holdings


def _parse_nav_per_share(page_html: str) -> float | None:
    idx = page_html.find("NAV per share")
    if idx == -1:
        return None
    window = page_html[idx : idx + _NAV_PER_SHARE_WINDOW_CHARS]
    for cell in _PARAGRAPH_RE.findall(window):
        m = re.search(r"\$([\d,]+\.?\d*)", cell)
        if m:
            try:
                return float(m.group(1).replace(",", ""))
            except ValueError:
                continue
    return None


def _parse_as_of_date(page_html: str) -> str | None:
    m = _AS_OF_RE.search(page_html)
    return m.group(1) if m else None


def parse_portfolio(page_html: str) -> RobostrategySnapshot:
    holdings = _parse_holdings(page_html)
    return RobostrategySnapshot(
        as_of=_parse_as_of_date(page_html),
        nav_per_share=_parse_nav_per_share(page_html),
        holdings=tuple(holdings),
    )
