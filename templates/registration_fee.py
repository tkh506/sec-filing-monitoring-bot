"""Standardized template for Form S-8 (employee benefit plan registration).

Since SEC's Filing Fee Modernization rule, registration statements ship a companion Inline-XBRL
"Fee Exhibit" instance document (filename ending "..._htm.xml") tagged under the "ffd" (Filing
Fee Disclosure) taxonomy, alongside the human-readable HTML exhibit. That XML is genuinely
structured -- fixed tag names, same reliability class as the ownership-form XML or companyfacts
XBRL -- validated live against real MSFT/AAPL/AMD/CRM S-8 filings. This is deliberately NOT built
on regex/HTML-table scraping of the human-readable exhibit: an earlier prototype of that approach
was tested against a real filing and failed (SEC's fee-table HTML interleaves column headers and
data in a way that simple proximity regex can't reliably associate) -- the fee exhibit's raw HTML
is only used as a fallback signal for locating the XML sibling file, never parsed for values.

Only applies to filings that have this XML fee exhibit -- older S-8s (roughly pre-2024) predate
the mandatory XBRL tagging and won't match, which is fine since this bot only alerts on new
filings going forward.
"""
import html
import re
from xml.etree import ElementTree as ET

from edgar_client import EdgarFetchError, build_document_url
from models import Filing, TemplateResult
from . import FilingTemplate, register

_FORMS = {"S-8"}
_FEE_XML_RE = re.compile(r"(filingfee|ex.*?107|107.*?ex).*\.xml$", re.IGNORECASE)


def _matches(filing: Filing) -> bool:
    return filing.form in _FORMS


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _sum_local(root, name: str) -> float | None:
    vals = []
    for el in root.iter():
        if _local_name(el.tag) == name and el.text:
            try:
                vals.append(float(el.text.strip()))
            except ValueError:
                continue
    return sum(vals) if vals else None


def _first_local_text(root, name: str) -> str | None:
    for el in root.iter():
        if _local_name(el.tag) == name and el.text:
            return el.text.strip()
    return None


async def _find_fee_xml_url(filing: Filing, edgar) -> str | None:
    try:
        index = await edgar.get_filing_index(filing.cik, filing.accession_no)
    except EdgarFetchError:
        return None
    for item in index.get("directory", {}).get("item", []):
        name = item.get("name", "")
        if _FEE_XML_RE.search(name):
            return build_document_url(filing.cik, filing.accession_no, name)
    return None


async def _render(filing: Filing, edgar) -> TemplateResult | None:
    fee_xml_url = await _find_fee_xml_url(filing, edgar)
    if fee_xml_url is None:
        return None

    try:
        xml_text = await edgar.fetch_filing_text(fee_xml_url, max_chars=200_000)
        root = ET.fromstring(xml_text)
    except Exception:
        return None

    shares_registered = _sum_local(root, "AmtSctiesRegd")
    total_offering = _first_local_text(root, "TtlOfferingAmt")
    security_title = _first_local_text(root, "OfferingSctyTitl")

    if shares_registered is None and total_offering is None:
        return None  # couldn't find the numbers we care about -- fall back to generic

    lines = [f"📋 <b>[{filing.ticker}] Registration (Form S-8)</b> — filed {filing.filed_date}"]
    if security_title:
        lines.append(f"Security: {html.escape(security_title)}")
    if shares_registered is not None:
        lines.append(f"Shares registered: {int(shares_registered):,}")
    if total_offering is not None:
        try:
            lines.append(f"Max aggregate offering price: ${float(total_offering):,.0f}")
        except ValueError:
            pass
    lines.append(f'<a href="{filing.filing_index_url}">View filing</a>')
    return TemplateResult(text="\n".join(lines))


register(FilingTemplate(name="registration_fee", matches=_matches, render=_render))
