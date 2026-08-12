from robostrategy_client import Holding, RobostrategySnapshot
from robostrategy_monitor import diff_snapshots


def _snapshot(holdings: list[Holding], nav_per_share: float | None = 10.00, as_of: str = "June 30, 2026"):
    return RobostrategySnapshot(as_of=as_of, nav_per_share=nav_per_share, holdings=tuple(holdings))


def test_no_change_produces_empty_diff():
    holdings = [Holding("Standard Bots", "Industrial Automation", 86_999_971, 35.0)]
    previous = _snapshot(holdings)
    current = _snapshot(holdings)
    assert diff_snapshots(previous, current) == []


def test_added_company():
    previous = _snapshot([Holding("Standard Bots", "Industrial Automation", 86_999_971, 35.0)])
    current = _snapshot(
        [
            Holding("Standard Bots", "Industrial Automation", 86_999_971, 35.0),
            Holding("New Co", "Robotics Infrastructure", 1_000_000, 1.0),
        ]
    )
    lines = diff_snapshots(previous, current)
    assert len(lines) == 1
    assert "➕ Added: New Co" in lines[0]
    assert "$1,000,000" in lines[0]
    assert "1.0% of NAV" in lines[0]


def test_removed_company():
    previous = _snapshot(
        [
            Holding("Standard Bots", "Industrial Automation", 86_999_971, 35.0),
            Holding("Gone Co", "Logistics", 500_000, 0.5),
        ]
    )
    current = _snapshot([Holding("Standard Bots", "Industrial Automation", 86_999_971, 35.0)])
    lines = diff_snapshots(previous, current)
    assert lines == ["➖ Removed: Gone Co"]


def test_fair_value_and_pct_change():
    previous = _snapshot([Holding("Standard Bots", "Industrial Automation", 80_000_000, 32.0)])
    current = _snapshot([Holding("Standard Bots", "Industrial Automation", 90_000_000, 36.0)])
    lines = diff_snapshots(previous, current)
    assert len(lines) == 1
    assert "$80,000,000 → $90,000,000" in lines[0]
    assert "32.0% → 36.0%" in lines[0]


def test_nav_per_share_change():
    previous = _snapshot([Holding("Standard Bots", "Industrial Automation", 86_999_971, 35.0)], nav_per_share=10.00)
    current = _snapshot([Holding("Standard Bots", "Industrial Automation", 86_999_971, 35.0)], nav_per_share=10.51)
    lines = diff_snapshots(previous, current)
    assert len(lines) == 1
    assert "$10.00 → $10.51" in lines[0]
    assert "+5.1%" in lines[0]


def test_tiny_float_noise_is_not_reported_as_a_change():
    previous = _snapshot([Holding("Standard Bots", "Industrial Automation", 86_999_971.0, 35.00)], nav_per_share=10.510)
    current = _snapshot([Holding("Standard Bots", "Industrial Automation", 86_999_971.001, 35.001)], nav_per_share=10.5101)
    assert diff_snapshots(previous, current) == []


# RoboStrategy's page no longer publishes fair value or NAV per share (2026-07 redesign) -- these
# cover the resulting fair_value=None / nav_per_share=None reality, which is what the parser
# actually produces today. The tests above (with real numbers) cover the same logic paths in case
# the site ever brings those figures back -- both must keep working.

def test_added_company_without_fair_value_omits_dollar_amount():
    previous = _snapshot([Holding("Standard Bots", "Industrial Automation", None, 35.0)], nav_per_share=None)
    current = _snapshot(
        [
            Holding("Standard Bots", "Industrial Automation", None, 35.0),
            Holding("New Co", "Robotics Infrastructure", None, 1.0),
        ],
        nav_per_share=None,
    )
    lines = diff_snapshots(previous, current)
    assert lines == ["➕ Added: New Co (Robotics Infrastructure) — 1.0% of NAV"]


def test_pct_change_without_fair_value_shows_only_percentages():
    previous = _snapshot([Holding("Standard Bots", "Industrial Automation", None, 32.0)], nav_per_share=None)
    current = _snapshot([Holding("Standard Bots", "Industrial Automation", None, 36.0)], nav_per_share=None)
    lines = diff_snapshots(previous, current)
    assert lines == ["Standard Bots: 32.0% → 36.0% of NAV"]


def test_no_nav_per_share_line_when_both_sides_are_none():
    previous = _snapshot([Holding("Standard Bots", "Industrial Automation", None, 35.0)], nav_per_share=None)
    current = _snapshot([Holding("Standard Bots", "Industrial Automation", None, 36.0)], nav_per_share=None)
    lines = diff_snapshots(previous, current)
    assert not any("NAV per share" in line for line in lines)
