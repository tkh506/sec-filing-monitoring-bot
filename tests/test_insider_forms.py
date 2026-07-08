import pytest

from models import Filing
from templates.insider_forms import _matches, _render

# Trimmed fixture matching the real schema (validated live against an actual NVDA Form 4).
FORM4_XML = """<?xml version="1.0"?>
<ownershipDocument>
    <documentType>4</documentType>
    <reportingOwner>
        <reportingOwnerId>
            <rptOwnerCik>0001197647</rptOwnerCik>
            <rptOwnerName>COXE TENCH</rptOwnerName>
        </reportingOwnerId>
        <reportingOwnerRelationship>
            <isDirector>1</isDirector>
            <isOfficer>0</isOfficer>
            <isTenPercentOwner>0</isTenPercentOwner>
            <isOther>0</isOther>
        </reportingOwnerRelationship>
    </reportingOwner>
    <nonDerivativeTable>
        <nonDerivativeTransaction>
            <securityTitle><value>Common</value></securityTitle>
            <transactionCoding><transactionCode>G</transactionCode></transactionCoding>
            <transactionAmounts>
                <transactionShares><value>500000</value></transactionShares>
                <transactionPricePerShare><value>0</value></transactionPricePerShare>
                <transactionAcquiredDisposedCode><value>D</value></transactionAcquiredDisposedCode>
            </transactionAmounts>
            <postTransactionAmounts>
                <sharesOwnedFollowingTransaction><value>25171360</value></sharesOwnedFollowingTransaction>
            </postTransactionAmounts>
        </nonDerivativeTransaction>
    </nonDerivativeTable>
    <derivativeTable></derivativeTable>
</ownershipDocument>"""

# Real NVDA Form 3 example: reporting person owned nothing at the time -- both tables empty.
FORM3_EMPTY_XML = """<?xml version="1.0"?>
<ownershipDocument>
    <documentType>3</documentType>
    <noSecuritiesOwned>1</noSecuritiesOwned>
    <reportingOwner>
        <reportingOwnerId><rptOwnerCik>1</rptOwnerCik><rptOwnerName>GAWEL SCOTT</rptOwnerName></reportingOwnerId>
        <reportingOwnerRelationship>
            <isDirector>0</isDirector><isOfficer>1</isOfficer><isTenPercentOwner>0</isTenPercentOwner><isOther>0</isOther>
            <officerTitle>Principal Accounting Officer</officerTitle>
        </reportingOwnerRelationship>
    </reportingOwner>
    <nonDerivativeTable></nonDerivativeTable>
    <derivativeTable></derivativeTable>
</ownershipDocument>"""

FORM3_WITH_HOLDINGS_XML = """<?xml version="1.0"?>
<ownershipDocument>
    <documentType>3</documentType>
    <reportingOwner>
        <reportingOwnerId><rptOwnerCik>1</rptOwnerCik><rptOwnerName>JANE DOE</rptOwnerName></reportingOwnerId>
        <reportingOwnerRelationship>
            <isDirector>0</isDirector><isOfficer>1</isOfficer><isTenPercentOwner>0</isTenPercentOwner><isOther>0</isOther>
            <officerTitle>Chief Financial Officer</officerTitle>
        </reportingOwnerRelationship>
    </reportingOwner>
    <nonDerivativeTable>
        <nonDerivativeHolding>
            <securityTitle><value>Common Stock</value></securityTitle>
            <postTransactionAmounts>
                <sharesOwnedFollowingTransaction><value>12345</value></sharesOwnedFollowingTransaction>
            </postTransactionAmounts>
        </nonDerivativeHolding>
    </nonDerivativeTable>
    <derivativeTable></derivativeTable>
</ownershipDocument>"""


class FakeEdgar:
    def __init__(self, xml_text):
        self.xml_text = xml_text

    async def fetch_filing_text(self, url, max_chars=40000):
        return self.xml_text


def _filing(form: str, accn: str = "0001-26-000001") -> Filing:
    return Filing(
        cik="1045810", accession_no=accn, form=form, filed_date="2026-07-06",
        primary_document="xslF345X06/wk-form4_x.xml", ticker="NVDA",
    )


def test_matches_ownership_forms():
    for form in ("3", "3/A", "4", "4/A", "5", "5/A"):
        assert _matches(_filing(form))
    assert not _matches(_filing("8-K"))
    assert not _matches(_filing("10-Q"))


@pytest.mark.asyncio
async def test_render_form4_transaction():
    result = await _render(_filing("4"), FakeEdgar(FORM4_XML))
    assert result is not None
    assert "COXE TENCH" in result.text
    assert "Director" in result.text
    assert "500,000 sh" in result.text
    assert "25,171,360" in result.text


@pytest.mark.asyncio
async def test_render_form3_no_holdings_falls_back_to_none():
    result = await _render(_filing("3"), FakeEdgar(FORM3_EMPTY_XML))
    assert result is None


@pytest.mark.asyncio
async def test_render_form3_with_holdings():
    result = await _render(_filing("3"), FakeEdgar(FORM3_WITH_HOLDINGS_XML))
    assert result is not None
    assert "JANE DOE" in result.text
    assert "Officer (Chief Financial Officer)" in result.text
    assert "12,345 sh" in result.text


@pytest.mark.asyncio
async def test_render_malformed_xml_returns_none():
    result = await _render(_filing("4"), FakeEdgar("not xml at all"))
    assert result is None
