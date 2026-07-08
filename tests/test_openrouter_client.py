from openrouter_client import _clean_filing_text


def test_strips_tags_and_unescapes_entities():
    raw = "<html><body><p>Net income increased&nbsp;5%&#58; a &amp; b</p></body></html>"
    cleaned = _clean_filing_text(raw)
    assert "<" not in cleaned and ">" not in cleaned
    assert "Net income increased" in cleaned
    assert "&amp;" not in cleaned
    assert "a & b" in cleaned


def test_collapses_whitespace():
    raw = "<p>Line one</p>\n\n\n<p>   Line   two   </p>"
    cleaned = _clean_filing_text(raw)
    assert "  " not in cleaned
    assert cleaned == "Line one Line two"


def test_truncates_to_max_chars():
    raw = "<p>" + ("x" * 100) + "</p>"
    cleaned = _clean_filing_text(raw, max_chars=10)
    assert len(cleaned) == 10
