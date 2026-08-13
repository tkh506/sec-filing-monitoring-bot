"""Fetch + parse RoboStrategy's public portfolio page (https://robostrategy.co/portfolio).

Unlike SEC EDGAR, this is a marketing website's own HTML with no schema guarantee -- there's no
regulator-mandated taxonomy behind it, just whatever markup RoboStrategy's Framer site happens to
emit today. Parsing is deliberately defensive: any structural surprise raises
RobostrategyParseError rather than silently returning wrong or partial data, so the caller can
alert "couldn't parse, check manually" instead of going quiet.

NOTE (observed 2026-07): RoboStrategy redesigned this page and removed the per-holding dollar Fair
Value column from the table -- `Holding.fair_value` is therefore always None now (kept as an
optional field, not dropped, in case a future redesign brings it back). Total NAV and NAV per
share are NOT gone, though -- they moved out of the old dedicated stat widget into a plain prose
footnote sentence elsewhere on the page ("...Net Assets Applicable to Common Shares of $X as of
[date]... net asset value as of [date], is $Y per share..."), which is what
`_parse_total_nav`/`_parse_nav_per_share` now extract. Note this prose sentence can carry a more
recent "as of" date (`RobostrategySnapshot.nav_as_of`) than the holdings table's own `as_of` date
-- the fund's overall NAV appears to update on a different cadence than the detailed holdings
breakdown. There's also a large embedded JSON blob further down the page with per-holding dollar
figures, structured as Framer's internal CMS export (obfuscated field-ID hashes, no stable schema,
and it appears to mix multiple report years per company) -- deliberately NOT parsed, too fragile
and ambiguous to trust; per-company Fair Value stays unavailable.

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
_TOTAL_NAV_RE = re.compile(
    r"Net Assets Applicable to Common Shares of \$([\d,]+(?:\.\d+)?)\s+as of\s+([A-Za-z]+\s+\d{1,2},\s*\d{4})"
)
_NAV_PER_SHARE_RE = re.compile(
    r"net asset value as of\s+([A-Za-z]+\s+\d{1,2},\s*\d{4}),\s*is\s*\$([\d,]+(?:\.\d+)?)\s*per share",
    re.IGNORECASE,
)
_ROW_WINDOW_CHARS = 2000

# Summary/total rows share the same row markup as real holdings. An empty Nature-of-Business
# field used to be enough to tell them apart, but RoboStrategy has since started filling in a
# dollar figure on the "Total Net Assets (NAV)" row's business-position cell, which slipped that
# row past the empty-business check and got it miscounted as a 100%-of-NAV holding. Belt and
# braces: exclude by known label too, not just the (no longer reliable on its own) empty-field
# heuristic, which stays as a fallback for any similarly-shaped row not in this list yet.
_NON_HOLDING_ROW_NAMES = {
    "Portfolio Company",  # header row
    "Total Investments",
    "Cash & cash equivalents",
    "Investments Paid in Advance",
    "Other assets, less liabilities",
    "Total Net Assets (NAV)",
}


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
    total_nav: float | None = None
    nav_as_of: str | None = None  # can differ from `as_of` -- see module docstring


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
        clean_name = html.unescape(name.strip())
        if clean_name in _NON_HOLDING_ROW_NAMES:
            continue
        business = business.strip()
        if not business:
            continue  # summary/total row not in the denylist yet, but still not a real holding
        pct_match = _PCT_RE.search(pct_raw)
        if not pct_match:
            continue  # e.g. the header row ("Nature of Business" / "% of Net Assets" as literal text)
        holdings.append(
            Holding(
                name=clean_name,
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


def _parse_total_nav(page_html: str) -> tuple[float | None, str | None]:
    """Returns (total_nav, as_of_date) from the "...Net Assets Applicable to Common Shares of $X
    as of [date]..." footnote sentence -- the old dedicated stat widget for this is gone, but the
    figure itself is still published here."""
    m = _TOTAL_NAV_RE.search(page_html)
    if not m:
        return None, None
    try:
        return float(m.group(1).replace(",", "")), m.group(2)
    except ValueError:
        return None, None


def _parse_nav_per_share(page_html: str) -> tuple[float | None, str | None]:
    """Returns (nav_per_share, as_of_date) from the "...net asset value as of [date], is $Y per
    share..." footnote sentence -- see _parse_total_nav."""
    m = _NAV_PER_SHARE_RE.search(page_html)
    if not m:
        return None, None
    try:
        return float(m.group(2).replace(",", "")), m.group(1)
    except ValueError:
        return None, None


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
    total_nav, total_nav_as_of = _parse_total_nav(page_html)
    nav_per_share, nav_per_share_as_of = _parse_nav_per_share(page_html)
    nav_as_of_raw = nav_per_share_as_of or total_nav_as_of
    nav_as_of = re.sub(r"\s+", " ", nav_as_of_raw).strip() if nav_as_of_raw else None
    return RobostrategySnapshot(
        as_of=_parse_as_of_date(page_html),
        nav_per_share=nav_per_share,
        holdings=tuple(holdings),
        total_nav=total_nav,
        nav_as_of=nav_as_of,
    )
