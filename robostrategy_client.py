"""Fetch + parse RoboStrategy's public portfolio page (https://robostrategy.co/portfolio).

Unlike SEC EDGAR, this is a marketing website's own HTML with no schema guarantee -- there's no
regulator-mandated taxonomy behind it, just whatever markup RoboStrategy's Framer site happens to
emit today. Parsing is deliberately defensive: any structural surprise raises
RobostrategyParseError rather than silently returning wrong or partial data, so the caller can
alert "couldn't parse, check manually" instead of going quiet.

NOTE (observed 2026-07): RoboStrategy redesigned this page and removed two data points it used to
publish here -- each holding's dollar Fair Value, and the fund's NAV per share. Only company
name/business/% of Net Assets remain. `Holding.fair_value` and `RobostrategySnapshot.nav_per_share`
are therefore always None now -- that's not a parse failure, the site simply stopped publishing
that data. robostrategy_monitor.py's diff/alert logic degrades gracefully around this (reports
only what's actually available); this client still accepts a fair_value if a future redesign
brings it back; nothing downstream assumes it's always None.

Row anchor: each holding's name cell is `data-framer-name="Name / Link"` (companies with their own
portfolio sub-page, name wrapped in an <a>) or plain `data-framer-name="Name"` (companies without
one, name in a plain <p>) -- both forms coexist on the real page. Framer duplicates the whole table
for a responsive-breakpoint variant (see _minimal_period). Summary/total rows sharing this same row
markup (e.g. "Total Investments", "Cash & cash equivalents", "Total Net Assets (NAV)") are filtered
out because they have an empty Nature-of-Business field, unlike real holdings.
"""
import html
import re
from dataclasses import dataclass

import httpx

PORTFOLIO_URL = "https://robostrategy.co/portfolio"

_NAME_MARKER_RE = re.compile(r'<div[^>]*data-framer-name="Name(?: / Link)?"[^>]*>(.*?)</div>', re.DOTALL)
_TEXT_IN_TAG_RE = re.compile(r"<(?:a|p)[^>]*>([^<]*)</(?:a|p)>")
_PARAGRAPH_RE = re.compile(r"<p[^>]*>([^<]*)</p>")
_FOOTNOTE_RE = re.compile(r"^(\([a-z0-9]+\))+$", re.IGNORECASE)
_PCT_RE = re.compile(r"(-?[\d.]+)%")
_AS_OF_RE = re.compile(r"As of ([A-Za-z]+ \d{1,2}, \d{4}) monthly NAV")
_ROW_WINDOW_CHARS = 2000
_NAV_PER_SHARE_WINDOW_CHARS = 1500


class RobostrategyParseError(Exception):
    pass


@dataclass(frozen=True)
class Holding:
    name: str
    business: str
    fair_value: float | None
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
    name_matches = list(_NAME_MARKER_RE.finditer(page_html))
    if not name_matches:
        raise RobostrategyParseError("No portfolio entries found -- page structure may have changed.")

    raw_rows = []
    for i, m in enumerate(name_matches):
        name_text_match = _TEXT_IN_TAG_RE.search(m.group(1))
        if name_text_match is None:
            raise RobostrategyParseError(f"Could not extract a name from row markup: {m.group(1)!r}")
        name = name_text_match.group(1)

        row_end = name_matches[i + 1].start() if i + 1 < len(name_matches) else m.end() + _ROW_WINDOW_CHARS
        rest_chunk = page_html[m.end() : min(row_end, m.end() + _ROW_WINDOW_CHARS)]
        rest_cells = _PARAGRAPH_RE.findall(rest_chunk)

        # rest_cells is [footnote?, business, pct, ...possible trailing bleed]. Footnote optional.
        if rest_cells and _FOOTNOTE_RE.match(rest_cells[0]):
            business = rest_cells[1] if len(rest_cells) > 1 else ""
            pct_raw = rest_cells[2] if len(rest_cells) > 2 else ""
        else:
            business = rest_cells[0] if len(rest_cells) > 0 else ""
            pct_raw = rest_cells[1] if len(rest_cells) > 1 else ""

        raw_rows.append((name, business, pct_raw))

    period = _minimal_period(raw_rows)
    unique_rows = raw_rows[:period]

    holdings = []
    for name, business, pct_raw in unique_rows:
        business = business.strip()
        if not business:
            continue  # summary/total row (e.g. "Total Investments"), not a real holding
        pct_match = _PCT_RE.search(pct_raw)
        if not pct_match:
            continue  # e.g. the header row ("Nature of Business" / "% of Net Assets" as literal text)
        holdings.append(
            Holding(
                name=html.unescape(name.strip()),
                business=html.unescape(business),
                fair_value=None,  # no longer published on the page -- see module docstring
                pct_nav=float(pct_match.group(1)),
            )
        )

    if not holdings:
        raise RobostrategyParseError(
            "Found row markers but no valid holdings after filtering -- page structure may have changed."
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


def _aggregate_by_company(holdings: list[Holding]) -> list[Holding]:
    """Merge multiple line items for the same company (e.g. separate funding-round holdings --
    the real page currently lists both Apptronik and Dexmate as two rows each) into one combined
    row per company. This is the granularity the diff/alert logic operates on (each *company's*
    fair value and % of NAV, per the user's framing), and it also sidesteps an entire class of
    bug: matching holdings by name alone is ambiguous when a name isn't unique, so aggregating
    upfront means every downstream consumer only ever sees one row per company."""
    order: list[str] = []
    business_by_name: dict[str, str] = {}
    fair_value_by_name: dict[str, float | None] = {}
    pct_by_name: dict[str, float] = {}
    for h in holdings:
        if h.name not in business_by_name:
            order.append(h.name)
            business_by_name[h.name] = h.business
            fair_value_by_name[h.name] = 0.0
            pct_by_name[h.name] = 0.0
        if h.fair_value is None or fair_value_by_name[h.name] is None:
            fair_value_by_name[h.name] = None
        else:
            fair_value_by_name[h.name] += h.fair_value
        pct_by_name[h.name] += h.pct_nav
    return [
        Holding(
            name=name,
            business=business_by_name[name],
            fair_value=fair_value_by_name[name],
            pct_nav=pct_by_name[name],
        )
        for name in order
    ]


def parse_portfolio(page_html: str) -> RobostrategySnapshot:
    holdings = _aggregate_by_company(_parse_holdings(page_html))
    return RobostrategySnapshot(
        as_of=_parse_as_of_date(page_html),
        nav_per_share=_parse_nav_per_share(page_html),
        holdings=tuple(holdings),
    )
