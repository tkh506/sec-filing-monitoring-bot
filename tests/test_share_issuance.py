from models import Filing
from templates.share_issuance import _matches, extract_share_issuance


def _companyfacts(units, taxonomy="dei", concept="EntityCommonStockSharesOutstanding"):
    return {"facts": {taxonomy: {concept: {"units": {"shares": units}}}}}


def test_extract_success_computes_delta_and_pct():
    units = [
        {"end": "2024-03-31", "val": 1000, "accn": "a1", "filed": "2024-05-01"},
        {"end": "2024-06-30", "val": 1100, "accn": "a2", "filed": "2024-08-01"},
    ]
    result = extract_share_issuance(_companyfacts(units), target_accn="a2", filing_date="2024-08-01")
    assert result is not None
    assert result.new_shares_issued == 100
    assert result.previous_outstanding == 1000
    assert result.total_outstanding == 1100
    assert abs(result.pct_change - 10.0) < 1e-6


def test_extract_returns_none_when_no_concept_present():
    assert extract_share_issuance({"facts": {}}, target_accn="a1", filing_date="2024-01-01") is None


def test_extract_returns_none_on_zero_baseline():
    units = [
        {"end": "2024-03-31", "val": 0, "accn": "a1", "filed": "2024-05-01"},
        {"end": "2024-06-30", "val": 1100, "accn": "a2", "filed": "2024-08-01"},
    ]
    assert extract_share_issuance(_companyfacts(units), target_accn="a2", filing_date="2024-08-01") is None


def test_extract_returns_none_with_no_prior_baseline():
    units = [{"end": "2024-06-30", "val": 1100, "accn": "a2", "filed": "2024-08-01"}]
    assert extract_share_issuance(_companyfacts(units), target_accn="a2", filing_date="2024-08-01") is None


def test_extract_falls_back_to_us_gaap_concept_when_dei_absent():
    units = [
        {"end": "2024-03-31", "val": 1000, "accn": "a1", "filed": "2024-05-01"},
        {"end": "2024-06-30", "val": 1200, "accn": "a2", "filed": "2024-08-01"},
    ]
    facts = _companyfacts(units, taxonomy="us-gaap", concept="CommonStockSharesOutstanding")
    result = extract_share_issuance(facts, target_accn="a2", filing_date="2024-08-01")
    assert result is not None
    assert result.new_shares_issued == 200


def test_matches_unconditional_forms():
    f = Filing(cik="1", accession_no="a", form="S-1", filed_date="2024-01-01", primary_document="d")
    assert _matches(f)


def test_does_not_match_10q_10k_anymore():
    # 10-Q/10-K moved to templates/financial_highlights.py (richer combined message); this
    # template must no longer claim them, or both templates would try to match the same filing.
    for form in ("10-Q", "10-K"):
        f = Filing(cik="1", accession_no="a", form=form, filed_date="2024-01-01", primary_document="d")
        assert not _matches(f)


def test_matches_8k_with_relevant_item():
    f = Filing(cik="1", accession_no="a", form="8-K", filed_date="2024-01-01", primary_document="d", items=("3.02",))
    assert _matches(f)


def test_does_not_match_8k_without_relevant_item():
    f = Filing(cik="1", accession_no="a", form="8-K", filed_date="2024-01-01", primary_document="d", items=("5.02",))
    assert not _matches(f)


def test_does_not_match_unrelated_form():
    f = Filing(cik="1", accession_no="a", form="4", filed_date="2024-01-01", primary_document="d")
    assert not _matches(f)
