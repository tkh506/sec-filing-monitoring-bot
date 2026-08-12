import pytest

from robostrategy_client import RobostrategyParseError, parse_portfolio

# Trimmed to mirror the real page's markup after RoboStrategy's 2026-07 redesign (validated live
# against https://robostrategy.co/portfolio): the old `data-framer-name="Portfolio Entry"` table
# was replaced by rows keyed on `data-framer-name="Name"` (plain <p>, no link to a company
# sub-page) or `"Name / Link"` (name wrapped in an <a>, both forms coexist), and the "Fair Value $"
# column plus the "NAV per share" figure were removed from the page entirely -- only company
# name/business/% of Net Assets remain.
def _row(name, footnote, business, pct, linked=True):
    if linked:
        name_cell = f'<div data-framer-name="Name / Link"><p><a href="./portfolio/x">{name}</a></p></div>'
    else:
        name_cell = f'<div data-framer-name="Name"><p>{name}</p></div>'
    footnote_html = f"<div><p>{footnote}</p></div>" if footnote else ""
    return (
        f'<div data-framer-name="Default">{name_cell}{footnote_html}'
        f"<div><p>{business}</p></div><div><p>{pct}</p></div></div>"
    )


def _summary_row(label, pct):
    """Rows like "Total Investments" / "Cash & cash equivalents" share the same row markup as
    real holdings but have an empty Nature-of-Business field -- that's how they're filtered out."""
    return (
        f'<div data-framer-name="Default"><div data-framer-name="Name"><p>{label}</p></div>'
        f"<div><p></p></div><div><p>{pct}</p></div></div>"
    )


_HEADER_ROW = (
    '<div data-framer-name="Default"><div data-framer-name="Name"><p>Portfolio Company</p></div>'
    '<div><p>Nature of Business</p></div><div><p>% of Net Assets</p></div></div>'
)

_UNIQUE_ROWS = (
    _row("Standard Bots", "(a)(b)(c)", "Industrial Automation", "35.0%", linked=True)
    + _row("Cyan Robotics, Inc.", "(a)(b)(c)(d)(e)", "Logistics", "0.6%", linked=False)
    + _summary_row("Total Investments", "96.8%")
)

_TABLE_BLOCK = _HEADER_ROW + _UNIQUE_ROWS

FIXTURE_HTML = f"""
<html><body>
<p>As of June 30, 2026 monthly NAV&nbsp;</p>
<div class="table">{_TABLE_BLOCK}{_TABLE_BLOCK}</div>
</body></html>
"""


def test_parses_as_of_date():
    snap = parse_portfolio(FIXTURE_HTML)
    assert snap.as_of == "June 30, 2026"


def test_nav_per_share_is_none_since_the_page_no_longer_publishes_it():
    snap = parse_portfolio(FIXTURE_HTML)
    assert snap.nav_per_share is None


def test_dedupes_responsive_duplicate_and_excludes_header_and_summary_rows():
    snap = parse_portfolio(FIXTURE_HTML)
    names = {h.name for h in snap.holdings}
    assert names == {"Standard Bots", "Cyan Robotics, Inc."}


def test_fair_value_is_none_since_the_column_was_removed():
    snap = parse_portfolio(FIXTURE_HTML)
    standard_bots = next(h for h in snap.holdings if h.name == "Standard Bots")
    assert standard_bots.fair_value is None
    assert standard_bots.business == "Industrial Automation"
    assert standard_bots.pct_nav == 35.0


def test_handles_row_without_a_link_to_a_company_subpage():
    snap = parse_portfolio(FIXTURE_HTML)
    cyan = next(h for h in snap.holdings if h.name == "Cyan Robotics, Inc.")
    assert cyan.business == "Logistics"
    assert cyan.pct_nav == 0.6


_NO_FOOTNOTE_TABLE = _HEADER_ROW + _row("NoFootnote Co", "", "Some Business", "1.0%")
NO_FOOTNOTE_FIXTURE_HTML = f"<html><body>{_NO_FOOTNOTE_TABLE}{_NO_FOOTNOTE_TABLE}</body></html>"


def test_handles_row_without_footnote_markers():
    snap = parse_portfolio(NO_FOOTNOTE_FIXTURE_HTML)
    no_footnote = next(h for h in snap.holdings if h.name == "NoFootnote Co")
    assert no_footnote.business == "Some Business"
    assert no_footnote.pct_nav == 1.0


_DUPLICATE_NAME_TABLE = _HEADER_ROW + _row(
    "Apptronik, Inc.", "(a)(b)(c)(d)", "Humanoid Robotics", "7.8%"
) + _row("Apptronik, Inc.", "(a)(b)(c)", "Humanoid Robotics", "7.1%")
DUPLICATE_NAME_FIXTURE_HTML = f"<html><body>{_DUPLICATE_NAME_TABLE}</body></html>"


def test_aggregates_multiple_holdings_of_the_same_company():
    # The real page currently lists Apptronik and Dexmate as two separate funding-round rows
    # each -- matching holdings by name alone (without aggregating first) is ambiguous and, as
    # discovered via a live-pipeline test, silently produces spurious "changed" diffs even when
    # nothing actually changed. Aggregating at parse time is the fix: one row per company.
    snap = parse_portfolio(DUPLICATE_NAME_FIXTURE_HTML)
    assert len(snap.holdings) == 1
    apptronik = snap.holdings[0]
    assert apptronik.name == "Apptronik, Inc."
    assert apptronik.pct_nav == pytest.approx(7.8 + 7.1)


def test_raises_on_no_entries_found():
    with pytest.raises(RobostrategyParseError):
        parse_portfolio("<html><body>nothing here</body></html>")


def test_raises_when_only_non_holding_rows_present():
    bad_html = f"<html><body>{_HEADER_ROW}{_summary_row('Total Investments', '96.8%')}</body></html>"
    with pytest.raises(RobostrategyParseError):
        parse_portfolio(bad_html)
