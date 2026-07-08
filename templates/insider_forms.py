"""Standardized template for Forms 3, 4, and 5 (beneficial ownership).

SEC's ownership-document XML schema (root element <ownershipDocument>) is fixed and identical
across all three forms -- validated live against real NVDA Form 3 and Form 4 filings -- so one
parser covers all of them. No XBRL/companyfacts involved; the data comes straight from the
filing's own raw XML (see models.Filing.raw_xml_url for why that's a different URL than the
human-readable viewer page).
"""
import html
from xml.etree import ElementTree as ET

from models import Filing, TemplateResult
from . import FilingTemplate, register

_FORMS = {"3", "3/A", "4", "4/A", "5", "5/A"}

_FORM_LABELS = {
    "3": "Initial Ownership Statement",
    "3/A": "Initial Ownership Statement (Amended)",
    "4": "Insider Transaction",
    "4/A": "Insider Transaction (Amended)",
    "5": "Annual Ownership Statement",
    "5/A": "Annual Ownership Statement (Amended)",
}

# Common Table I/II transaction codes (SEC Form 4 instructions, Rule 16a-3).
_TRANSACTION_CODES = {
    "P": "Open market purchase",
    "S": "Open market sale",
    "A": "Grant/award",
    "D": "Disposition to issuer",
    "F": "Tax withholding",
    "M": "Option exercise",
    "C": "Conversion of derivative",
    "G": "Gift",
    "X": "In-the-money option exercise",
    "J": "Other acquisition/disposition",
}


def _matches(filing: Filing) -> bool:
    return filing.form in _FORMS


def _text(el, path: str) -> str | None:
    node = el.find(path)
    return node.text.strip() if node is not None and node.text else None


def _esc(s: str | None) -> str:
    return html.escape(s) if s else ""


def _relationship(owner_el) -> str:
    rel = owner_el.find("reportingOwnerRelationship")
    if rel is None:
        return "Reporting Person"
    roles = []
    if _text(rel, "isDirector") == "1":
        roles.append("Director")
    if _text(rel, "isOfficer") == "1":
        title = _text(rel, "officerTitle")
        roles.append(f"Officer ({_esc(title)})" if title else "Officer")
    if _text(rel, "isTenPercentOwner") == "1":
        roles.append("10% Owner")
    if _text(rel, "isOther") == "1":
        roles.append("Other")
    return ", ".join(roles) if roles else "Reporting Person"


def _as_number(raw: str | None) -> float | None:
    if raw is None:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _fmt_shares(raw: str | None) -> str | None:
    val = _as_number(raw)
    if val is None:
        return None
    return f"{int(val):,}" if val == int(val) else f"{val:,.2f}"


def _format_transaction(tx) -> str:
    code = _text(tx, "transactionCoding/transactionCode") or "?"
    code_label = _TRANSACTION_CODES.get(code, "Transaction")
    shares = _fmt_shares(_text(tx, "transactionAmounts/transactionShares/value"))
    price = _as_number(_text(tx, "transactionAmounts/transactionPricePerShare/value"))
    ad_code = _text(tx, "transactionAmounts/transactionAcquiredDisposedCode/value")
    direction = {"A": "Acquired", "D": "Disposed"}.get(ad_code, "")
    owned_after = _fmt_shares(_text(tx, "postTransactionAmounts/sharesOwnedFollowingTransaction/value"))
    security = _esc(_text(tx, "securityTitle/value")) or "Common Stock"

    line = f"• {_esc(code_label)} ({code}): {direction}".strip()
    if shares:
        line += f" {shares} sh"
    line += f" of {security}"
    if price:
        line += f" @ ${price:,.2f}"
    if owned_after:
        line += f" (owns {owned_after} after)"
    return line


def _format_holding(holding) -> str:
    security = _esc(_text(holding, "securityTitle/value")) or "Common Stock"
    owned = _fmt_shares(_text(holding, "postTransactionAmounts/sharesOwnedFollowingTransaction/value"))
    if owned is None:
        return f"• Holds {security} (amount not reported)"
    return f"• Holds {owned} sh of {security}"


async def _render(filing: Filing, edgar) -> TemplateResult | None:
    try:
        xml_text = await edgar.fetch_filing_text(filing.raw_xml_url, max_chars=200_000)
        root = ET.fromstring(xml_text)
    except Exception:
        return None

    if root.tag != "ownershipDocument":
        return None

    owners = root.findall("reportingOwner")
    if not owners:
        return None

    owner_names = [_esc(_text(o, "reportingOwnerId/rptOwnerName")) or "Unknown" for o in owners]
    relationships = [_relationship(o) for o in owners]

    tx_lines = [_format_transaction(tx) for tx in root.findall("nonDerivativeTable/nonDerivativeTransaction")]
    tx_lines += [_format_transaction(tx) for tx in root.findall("derivativeTable/derivativeTransaction")]

    holding_lines = [_format_holding(h) for h in root.findall("nonDerivativeTable/nonDerivativeHolding")]
    holding_lines += [_format_holding(h) for h in root.findall("derivativeTable/derivativeHolding")]

    if not tx_lines and not holding_lines:
        return None  # nothing presentable -- fall back to generic

    label = _FORM_LABELS.get(filing.form, f"Form {filing.form}")
    lines = [
        f"👤 <b>[{filing.ticker}] {label}</b> — filed {filing.filed_date}",
        f"{'; '.join(owner_names)} ({'; '.join(relationships)})",
        "",
    ]
    if tx_lines:
        lines.append("Transactions:")
        lines.extend(tx_lines)
    if holding_lines:
        if tx_lines:
            lines.append("")
        lines.append("Holdings:")
        lines.extend(holding_lines)
    lines.append("")
    lines.append(f'<a href="{filing.filing_index_url}">View filing</a>')

    return TemplateResult(text="\n".join(lines))


register(FilingTemplate(name="insider_forms", matches=_matches, render=_render))
