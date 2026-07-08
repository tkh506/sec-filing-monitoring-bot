import pytest

from models import Filing
from templates.registration_fee import _matches, _render

# Trimmed fixture matching the real "ffd" Filing-Fee-Disclosure XBRL exhibit (validated live
# against a real MSFT S-8 filing's "..._htm.xml" fee exhibit).
FEE_XML = """<?xml version="1.0" encoding="utf-8"?>
<xbrl xmlns="http://www.xbrl.org/2003/instance" xmlns:ffd="http://xbrl.sec.gov/ffd/2025">
    <ffd:OfferingSctyTitl contextRef="offrl_1">Deferred Compensation Obligations</ffd:OfferingSctyTitl>
    <ffd:AmtSctiesRegd contextRef="offrl_1" unitRef="Shares">1200000000</ffd:AmtSctiesRegd>
    <ffd:MaxAggtOfferingPric contextRef="offrl_1" unitRef="USD">1200000000.00</ffd:MaxAggtOfferingPric>
    <ffd:TtlOfferingAmt contextRef="rc" unitRef="USD">1200000000.00</ffd:TtlOfferingAmt>
    <ffd:TtlFeeAmt contextRef="rc" unitRef="USD">165720.00</ffd:TtlFeeAmt>
</xbrl>"""


def _filing(form: str = "S-8") -> Filing:
    return Filing(
        cik="789019", accession_no="0001193125-25-337096", form=form, filed_date="2025-12-30",
        primary_document="d98304ds8.htm", ticker="MSFT",
    )


class FakeEdgar:
    def __init__(self, index_items, xml_text=FEE_XML):
        self.index_items = index_items
        self.xml_text = xml_text

    async def get_filing_index(self, cik, accession_no):
        return {"directory": {"item": [{"name": n} for n in self.index_items]}}

    async def fetch_filing_text(self, url, max_chars=40000):
        return self.xml_text


def test_matches_s8_only():
    assert _matches(_filing("S-8"))
    assert not _matches(_filing("S-1"))
    assert not _matches(_filing("10-Q"))


@pytest.mark.asyncio
async def test_render_finds_and_parses_fee_exhibit():
    edgar = FakeEdgar(["d98304ds8.htm", "d98304dexfilingfees.htm", "d98304dexfilingfees_htm.xml"])
    result = await _render(_filing(), edgar)
    assert result is not None
    assert "Shares registered: 1,200,000,000" in result.text
    assert "Max aggregate offering price: $1,200,000,000" in result.text
    assert "Deferred Compensation Obligations" in result.text


@pytest.mark.asyncio
async def test_render_returns_none_when_no_fee_exhibit_found():
    edgar = FakeEdgar(["d98304ds8.htm", "d98304dex231.htm"])  # no filingfees/107 file at all
    result = await _render(_filing(), edgar)
    assert result is None


@pytest.mark.asyncio
async def test_render_returns_none_on_malformed_xml():
    edgar = FakeEdgar(["exfilingfees_htm.xml"], xml_text="not xml")
    result = await _render(_filing(), edgar)
    assert result is None
