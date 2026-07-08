"""Standardized template: share issuance, extracted from XBRL companyfacts.

Returns None (never raises) whenever extraction can't produce a trustworthy
result -- the classifier treats None as "fall back to the generic template."
"""
from models import Filing, ShareIssuanceResult, TemplateResult
from . import FilingTemplate, register

# Forms that always warrant an extraction attempt. 10-Q/10-K are handled by the richer
# financial_highlights template instead (which reuses extract_share_issuance() below alongside
# revenue/net income/EPS), so they're deliberately excluded here to avoid double-matching.
_UNCONDITIONAL_FORMS = {
    "424B1", "424B2", "424B3", "424B4", "424B5",
    "S-1", "S-1/A", "S-3", "S-3/A",
}
# 8-K items that plausibly involve a change in shares outstanding.
_8K_SHARE_ITEMS = {"1.01", "3.02"}

# XBRL concepts to try, in priority order: (taxonomy, concept name).
_CONCEPT_PRIORITY = [
    ("dei", "EntityCommonStockSharesOutstanding"),
    ("us-gaap", "CommonStockSharesOutstanding"),
    ("us-gaap", "CommonStockSharesIssued"),
]


def _matches(filing: Filing) -> bool:
    if filing.form in _UNCONDITIONAL_FORMS:
        return True
    if filing.form == "8-K":
        return bool(_8K_SHARE_ITEMS & set(filing.items))
    return False


def _get_first_available_concept(companyfacts: dict) -> dict | None:
    facts = companyfacts.get("facts", {})
    for taxonomy, concept in _CONCEPT_PRIORITY:
        node = facts.get(taxonomy, {}).get(concept)
        if node:
            return node
    return None


def extract_share_issuance(
    companyfacts: dict, target_accn: str, filing_date: str
) -> ShareIssuanceResult | None:
    concept = _get_first_available_concept(companyfacts)
    if concept is None:
        return None

    units = concept.get("units", {}).get("shares", [])
    if not units:
        return None

    units_sorted = sorted(units, key=lambda u: (u.get("end", ""), u.get("filed", "")))

    after = next((u for u in units_sorted if u.get("accn") == target_accn), None)
    if after is None:
        candidates = [u for u in units_sorted if u.get("end", "") <= filing_date]
        after = candidates[-1] if candidates else None
    if after is None:
        return None

    after_filed = after.get("filed", filing_date)
    before_candidates = [
        u
        for u in units_sorted
        if u.get("filed", u.get("end", "")) < after_filed and u.get("accn") != after.get("accn")
    ]
    before = before_candidates[-1] if before_candidates else None
    if before is None:
        return None

    new_total = after.get("val")
    old_total = before.get("val")
    if not isinstance(new_total, (int, float)) or not isinstance(old_total, (int, float)):
        return None
    if old_total <= 0:
        return None

    delta = new_total - old_total
    pct_change = (delta / old_total) * 100

    return ShareIssuanceResult(
        new_shares_issued=int(delta),
        total_outstanding=int(new_total),
        previous_outstanding=int(old_total),
        pct_change=pct_change,
    )


def _format_message(filing: Filing, result: ShareIssuanceResult) -> str:
    sign = "+" if result.new_shares_issued >= 0 else ""
    return (
        f"📈 <b>[{filing.ticker}] Share Issuance</b> — {filing.form}, filed {filing.filed_date}\n"
        f"New shares issued: {sign}{result.new_shares_issued:,}\n"
        f"Total shares outstanding: {result.total_outstanding:,} (was {result.previous_outstanding:,})\n"
        f"Change: {sign}{result.pct_change:.2f}%\n"
        f"<a href=\"{filing.filing_index_url}\">View filing</a>"
    )


async def _render(filing: Filing, edgar) -> TemplateResult | None:
    try:
        companyfacts = await edgar.get_companyfacts(filing.cik)
    except Exception:
        return None
    result = extract_share_issuance(companyfacts, filing.accession_no, filing.filed_date)
    if result is None:
        return None
    return TemplateResult(text=_format_message(filing, result))


register(FilingTemplate(name="share_issuance", matches=_matches, render=_render))
