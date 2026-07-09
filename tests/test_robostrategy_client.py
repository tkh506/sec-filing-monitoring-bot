import pytest

from robostrategy_client import RobostrategyParseError, parse_portfolio

# Trimmed to mirror the real page's markup patterns (validated live against
# https://robostrategy.co/portfolio): repeated `data-framer-name="Portfolio Entry"` blocks each
# with 5 <p> cells (name, footnote, business, fair value, % of NAV), duplicated wholesale for a
# responsive-breakpoint variant, plus one row deliberately without footnote markers to exercise
# the field-shift fallback, and the separate "NAV per share" + "As of ... monthly NAV" markers.
def _entry(name, footnote, business, fair_value, pct):
    footnote_html = f"<div><p>{footnote}</p></div>" if footnote else ""
    return (
        f'<div data-framer-name="Portfolio Entry"><div><p>{name}</p></div>{footnote_html}'
        f"<div><p>{business}</p></div><div><p>{fair_value}</p></div><div><p>{pct}</p></div></div>"
    )


_UNIQUE_ENTRIES = (
    _entry("Standard Bots", "(a)(b)(c)", "Industrial Automation", "$86,999,971", "35.0%")
    + _entry("Figure AI, Inc.", "(a)(b)(c)(d)(e)", "Humanoid Robotics", "$37,250,000", "15.0%")
    + _entry("NoFootnote Co", "", "Some Business", "$1,000,000", "1.0%")
)

FIXTURE_HTML = f"""
<html><body>
<p>As of June 30, 2026 monthly NAV&nbsp;</p>
<div class="table">{_UNIQUE_ENTRIES}{_UNIQUE_ENTRIES}</div>
<p>NAV per share</p><div><p style="opacity:0">—</p></div><div><p>$10.51</p></div><div><p>—</p></div>
</body></html>
"""


def test_parses_as_of_date_and_nav_per_share():
    snap = parse_portfolio(FIXTURE_HTML)
    assert snap.as_of == "June 30, 2026"
    assert snap.nav_per_share == 10.51


def test_dedupes_responsive_duplicate_and_parses_all_fields():
    snap = parse_portfolio(FIXTURE_HTML)
    assert len(snap.holdings) == 3
    standard_bots = snap.holdings[0]
    assert standard_bots.name == "Standard Bots"
    assert standard_bots.business == "Industrial Automation"
    assert standard_bots.fair_value == 86_999_971
    assert standard_bots.pct_nav == 35.0


def test_handles_row_without_footnote_markers():
    snap = parse_portfolio(FIXTURE_HTML)
    no_footnote = next(h for h in snap.holdings if h.name == "NoFootnote Co")
    assert no_footnote.business == "Some Business"
    assert no_footnote.fair_value == 1_000_000
    assert no_footnote.pct_nav == 1.0


_DUPLICATE_NAME_ENTRIES = _entry(
    "Apptronik, Inc.", "(a)(b)(c)(d)", "Humanoid Robotics", "$19,503,143", "7.8%"
) + _entry("Apptronik, Inc.", "(a)(b)(c)", "Humanoid Robotics", "$17,746,859", "7.1%")

DUPLICATE_NAME_FIXTURE_HTML = f"""
<html><body>
<p>As of June 30, 2026 monthly NAV&nbsp;</p>
<div class="table">{_DUPLICATE_NAME_ENTRIES}</div>
<p>NAV per share</p><div><p>$10.51</p></div>
</body></html>
"""


def test_aggregates_multiple_holdings_of_the_same_company():
    # The real page currently lists Apptronik and Dexmate as two separate funding-round rows
    # each -- matching holdings by name alone (without aggregating first) is ambiguous and, as
    # discovered via a live-pipeline test, silently produces spurious "changed" diffs even when
    # nothing actually changed. Aggregating at parse time is the fix: one row per company.
    snap = parse_portfolio(DUPLICATE_NAME_FIXTURE_HTML)
    assert len(snap.holdings) == 1
    apptronik = snap.holdings[0]
    assert apptronik.name == "Apptronik, Inc."
    assert apptronik.fair_value == 19_503_143 + 17_746_859
    assert apptronik.pct_nav == pytest.approx(7.8 + 7.1)


def test_raises_on_no_entries_found():
    with pytest.raises(RobostrategyParseError):
        parse_portfolio("<html><body>nothing here</body></html>")


def test_raises_on_malformed_row():
    bad_html = '<div data-framer-name="Portfolio Entry"><div><p>OnlyOneCell</p></div></div>'
    with pytest.raises(RobostrategyParseError):
        parse_portfolio(bad_html)
