"""Standardized template for 10-Q/10-K periodic reports: key financial figures (revenue, net
income, EPS) pulled from XBRL companyfacts for the specific filing's own reported period, plus
the shares-outstanding change already computed by share_issuance.extract_share_issuance().

Picking "this filing's own number" out of companyfacts: every concept lists many periods'
worth of facts (current + prior-year comparisons, quarterly + year-to-date), all sharing the
same `accn` once tagged as part of this filing. Validated live against NVDA's most recent 10-Q --
among same-accn entries, the current period is reliably the one with the latest `end` date, and
(for Q2/Q3 filings, which tag both a quarterly and a year-to-date number under the same end date)
the shortest duration among those disambiguates quarterly from cumulative YTD.
"""
from datetime import date

from models import Filing, TemplateResult
from templates.share_issuance import extract_share_issuance
from . import FilingTemplate, register

_FORMS = {"10-Q", "10-Q/A", "10-K", "10-K/A"}

_REVENUE_CONCEPTS = [
    ("us-gaap", "RevenueFromContractWithCustomerExcludingAssessedTax"),
    ("us-gaap", "Revenues"),
    ("us-gaap", "RevenueFromContractWithCustomerIncludingAssessedTax"),
]
_NET_INCOME_CONCEPTS = [("us-gaap", "NetIncomeLoss")]
_EPS_BASIC_CONCEPTS = [("us-gaap", "EarningsPerShareBasic")]
_EPS_DILUTED_CONCEPTS = [("us-gaap", "EarningsPerShareDiluted")]


def _matches(filing: Filing) -> bool:
    return filing.form in _FORMS


def _duration_days(unit: dict) -> int:
    try:
        start = date.fromisoformat(unit.get("start", unit["end"]))
        end = date.fromisoformat(unit["end"])
        return (end - start).days
    except (KeyError, ValueError):
        return 0


def _pick_value(companyfacts: dict, concepts: list[tuple[str, str]], unit_key: str, target_accn: str) -> float | None:
    facts = companyfacts.get("facts", {})
    for taxonomy, concept in concepts:
        node = facts.get(taxonomy, {}).get(concept)
        if not node:
            continue
        units = node.get("units", {}).get(unit_key, [])
        matches = [u for u in units if u.get("accn") == target_accn and isinstance(u.get("val"), (int, float))]
        if not matches:
            continue
        max_end = max(u["end"] for u in matches if u.get("end"))
        same_end = [u for u in matches if u.get("end") == max_end]
        same_end.sort(key=_duration_days)
        return same_end[0]["val"]
    return None


def _fmt_money(val: float) -> str:
    sign = "-" if val < 0 else ""
    abs_val = abs(val)
    if abs_val >= 1_000_000_000:
        return f"{sign}${abs_val / 1_000_000_000:,.2f}B"
    if abs_val >= 1_000_000:
        return f"{sign}${abs_val / 1_000_000:,.1f}M"
    return f"{sign}${abs_val:,.0f}"


async def _render(filing: Filing, edgar) -> TemplateResult | None:
    try:
        companyfacts = await edgar.get_companyfacts(filing.cik)
    except Exception:
        return None

    revenue = _pick_value(companyfacts, _REVENUE_CONCEPTS, "USD", filing.accession_no)
    net_income = _pick_value(companyfacts, _NET_INCOME_CONCEPTS, "USD", filing.accession_no)
    eps_basic = _pick_value(companyfacts, _EPS_BASIC_CONCEPTS, "USD/shares", filing.accession_no)
    eps_diluted = _pick_value(companyfacts, _EPS_DILUTED_CONCEPTS, "USD/shares", filing.accession_no)
    share_result = extract_share_issuance(companyfacts, filing.accession_no, filing.filed_date)

    if revenue is None and net_income is None and eps_basic is None and share_result is None:
        return None  # nothing usable at all -- fall back to generic

    lines = [f"📊 <b>[{filing.ticker}] Financial Highlights</b> — {filing.form}, filed {filing.filed_date}"]
    if revenue is not None:
        lines.append(f"Revenue: {_fmt_money(revenue)}")
    if net_income is not None:
        lines.append(f"Net income: {_fmt_money(net_income)}")
    if eps_basic is not None or eps_diluted is not None:
        parts = []
        if eps_basic is not None:
            parts.append(f"{eps_basic:.2f} basic")
        if eps_diluted is not None:
            parts.append(f"{eps_diluted:.2f} diluted")
        lines.append(f"EPS: {' / '.join(parts)}")
    if share_result is not None:
        sign = "+" if share_result.new_shares_issued >= 0 else ""
        lines.append(
            f"Shares outstanding: {share_result.total_outstanding:,} "
            f"({sign}{share_result.pct_change:.2f}% vs prior period)"
        )
    lines.append(f'<a href="{filing.filing_index_url}">View filing</a>')
    return TemplateResult(text="\n".join(lines))


register(FilingTemplate(name="financial_highlights", matches=_matches, render=_render))
