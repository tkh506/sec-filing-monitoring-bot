from models import Filing
from poller import MAX_BACKFILL, _filings_since


def _make_filings(accession_numbers: list[str]) -> list[Filing]:
    """newest-first, matching EDGAR's own ordering."""
    return [
        Filing(cik="0000000001", accession_no=a, form="8-K", filed_date="2024-01-01", primary_document="d.htm")
        for a in accession_numbers
    ]


def test_no_new_filings_when_last_seen_is_newest():
    filings = _make_filings(["3", "2", "1"])
    assert _filings_since(filings, "3") == []


def test_returns_only_filings_newer_than_last_seen_in_order():
    filings = _make_filings(["5", "4", "3", "2", "1"])
    result = _filings_since(filings, "3")
    assert [f.accession_no for f in result] == ["5", "4"]


def test_none_last_seen_defensive_fallback_returns_newest_only():
    filings = _make_filings(["2", "1"])
    result = _filings_since(filings, None)
    assert [f.accession_no for f in result] == ["2"]


def test_empty_recent_filings_returns_empty():
    assert _filings_since([], "1") == []


def test_backfill_capped_when_last_seen_not_found_in_window():
    accession_numbers = [str(i) for i in range(20, 0, -1)]  # 20..1, newest first
    filings = _make_filings(accession_numbers)
    result = _filings_since(filings, "not-present")
    assert len(result) == MAX_BACKFILL
    assert [f.accession_no for f in result] == accession_numbers[:MAX_BACKFILL]
