from robostrategy_client import Holding, RobostrategySnapshot
from robostrategy_monitor import build_portfolio_summary


def _snapshot(
    holdings: list[Holding],
    nav_per_share: float | None = 10.00,
    as_of: str = "June 30, 2026",
    total_nav: float | None = None,
):
    return RobostrategySnapshot(
        as_of=as_of, nav_per_share=nav_per_share, holdings=tuple(holdings), total_nav=total_nav
    )


def _holding(name: str, pct_nav: float, business: str = "Some Business") -> Holding:
    return Holding(name, business, None, pct_nav)


# --- no change at all -------------------------------------------------------

def test_no_change_everywhere_reports_no_change_and_restates_nav():
    holdings = [_holding("Standard Bots", 35.0)]
    previous = _snapshot(holdings, nav_per_share=10.51, total_nav=274_578_031)
    current = _snapshot(holdings, nav_per_share=10.51, total_nav=274_578_031)
    summary = build_portfolio_summary(previous, current)
    assert summary.composition_text == "No Change"
    assert summary.pct_change_text == "No Change"
    assert summary.nav_text == "No Change. Total NAV: $274,578,031, NAV per share: $10.51"
    assert summary.has_any_change is False


def test_no_change_with_no_nav_data_available():
    holdings = [_holding("Standard Bots", 35.0)]
    previous = _snapshot(holdings, nav_per_share=None, total_nav=None)
    current = _snapshot(holdings, nav_per_share=None, total_nav=None)
    summary = build_portfolio_summary(previous, current)
    assert summary.nav_text == "No Change"


# --- composition: 1-2 vs >2 --------------------------------------------------

def test_composition_one_added_reports_name_and_pct():
    previous = _snapshot([_holding("Standard Bots", 35.0)])
    current = _snapshot([_holding("Standard Bots", 35.0), _holding("New Co", 1.0, "Robotics")])
    summary = build_portfolio_summary(previous, current)
    assert summary.composition_text == "➕ Added: New Co (1.0% of NAV)"
    assert summary.has_any_change is True


def test_composition_one_removed_reports_name_and_former_pct():
    previous = _snapshot([_holding("Standard Bots", 35.0), _holding("Gone Co", 0.5)])
    current = _snapshot([_holding("Standard Bots", 35.0)])
    summary = build_portfolio_summary(previous, current)
    assert summary.composition_text == "➖ Removed: Gone Co (was 0.5% of NAV)"


def test_composition_two_added_and_two_removed_lists_all():
    previous = _snapshot([_holding("A", 1.0), _holding("B", 2.0)])
    current = _snapshot([_holding("C", 3.0), _holding("D", 4.0)])
    summary = build_portfolio_summary(previous, current)
    assert "➕ Added: C (3.0% of NAV); D (4.0% of NAV)" in summary.composition_text
    assert "➖ Removed: A (was 1.0% of NAV); B (was 2.0% of NAV)" in summary.composition_text


def test_composition_more_than_two_added_summarizes_top_two():
    previous = _snapshot([_holding("Base", 50.0)])
    current = _snapshot(
        [
            _holding("Base", 50.0),
            _holding("Small", 1.0),
            _holding("Big", 10.0),
            _holding("Medium", 5.0),
        ]
    )
    summary = build_portfolio_summary(previous, current)
    assert summary.composition_text == "➕ 3 companies added, including Big (10.0% of NAV) and Medium (5.0% of NAV)"


def test_composition_more_than_two_removed_summarizes_top_two_by_former_pct():
    previous = _snapshot(
        [
            _holding("Base", 50.0),
            _holding("Small", 1.0),
            _holding("Big", 10.0),
            _holding("Medium", 5.0),
        ]
    )
    current = _snapshot([_holding("Base", 50.0)])
    summary = build_portfolio_summary(previous, current)
    assert (
        summary.composition_text
        == "➖ 3 companies removed, including Big (was 10.0% of NAV) and Medium (was 5.0% of NAV)"
    )


# --- % of NAV changes: 1-2 vs >2 ---------------------------------------------

def test_pct_change_two_companies_lists_both_with_before_after():
    previous = _snapshot([_holding("A", 30.0), _holding("B", 10.0)])
    current = _snapshot([_holding("A", 33.0), _holding("B", 8.0)])
    summary = build_portfolio_summary(previous, current)
    assert summary.pct_change_text == "A: 30.0% → 33.0%\nB: 10.0% → 8.0%"


def test_pct_change_more_than_two_summarizes_top_two_by_absolute_delta():
    previous = _snapshot(
        [_holding("A", 30.0), _holding("B", 10.0), _holding("C", 5.0), _holding("D", 2.0)]
    )
    current = _snapshot(
        [_holding("A", 30.5), _holding("B", 4.0), _holding("C", 5.1), _holding("D", 6.0)]
    )
    summary = build_portfolio_summary(previous, current)
    # All 4 moved beyond the epsilon; B moved by 6.0 (largest) and D by 4.0 (second largest) win
    # the top-2 spots over A (0.5) and C (0.1).
    assert summary.pct_change_text == "4 companies had % of NAV changes, including B (10.0% → 4.0%) and D (2.0% → 6.0%)"


def test_no_pct_change_reports_no_change():
    holdings = [_holding("A", 30.0)]
    previous = _snapshot(holdings)
    current = _snapshot(holdings)
    summary = build_portfolio_summary(previous, current)
    assert summary.pct_change_text == "No Change"


# --- Total NAV & NAV per share -----------------------------------------------

def test_nav_section_shows_both_figures_when_either_changes():
    holdings = [_holding("A", 30.0)]
    previous = _snapshot(holdings, nav_per_share=10.00, total_nav=270_000_000)
    current = _snapshot(holdings, nav_per_share=10.51, total_nav=274_578_031)
    summary = build_portfolio_summary(previous, current)
    assert summary.nav_text == "Total NAV: $270,000,000 → $274,578,031\nNAV per share: $10.00 → $10.51"
    assert summary.has_any_change is True


def test_nav_section_shows_both_figures_when_only_total_nav_changes():
    holdings = [_holding("A", 30.0)]
    previous = _snapshot(holdings, nav_per_share=10.00, total_nav=270_000_000)
    current = _snapshot(holdings, nav_per_share=10.00, total_nav=274_578_031)
    summary = build_portfolio_summary(previous, current)
    assert "Total NAV: $270,000,000 → $274,578,031" in summary.nav_text
    assert "NAV per share: $10.00 → $10.00" in summary.nav_text


# --- overall message -----------------------------------------------------

def test_has_any_change_false_when_nothing_moved():
    holdings = [_holding("A", 30.0)]
    previous = _snapshot(holdings, nav_per_share=10.0, total_nav=270_000_000)
    current = _snapshot(holdings, nav_per_share=10.0, total_nav=270_000_000)
    summary = build_portfolio_summary(previous, current)
    assert summary.has_any_change is False


def test_has_any_change_true_when_only_nav_moved():
    holdings = [_holding("A", 30.0)]
    previous = _snapshot(holdings, nav_per_share=10.0, total_nav=270_000_000)
    current = _snapshot(holdings, nav_per_share=10.51, total_nav=270_000_000)
    summary = build_portfolio_summary(previous, current)
    assert summary.composition_text == "No Change"
    assert summary.pct_change_text == "No Change"
    assert summary.has_any_change is True
