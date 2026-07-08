import pytest

from models import Filing
from templates.financial_highlights import _matches, _pick_value, _render

TARGET_ACCN = "0001045810-26-000052"

# Trimmed fixture matching the real shape returned for NVDA's most recent 10-Q: each concept
# carries a current-period entry and a prior-year comparison entry, both tagged with the same accn.
def _companyfacts():
    def _series(current_val, prior_val, unit_key="USD"):
        return {
            "units": {
                unit_key: [
                    {"start": "2025-01-27", "end": "2025-04-27", "val": prior_val, "accn": TARGET_ACCN},
                    {"start": "2026-01-26", "end": "2026-04-26", "val": current_val, "accn": TARGET_ACCN},
                ]
            }
        }

    return {
        "facts": {
            "us-gaap": {
                "Revenues": _series(81615000000, 44062000000),
                "NetIncomeLoss": _series(58321000000, 18775000000),
                "EarningsPerShareBasic": _series(2.40, 0.77, unit_key="USD/shares"),
                "EarningsPerShareDiluted": _series(2.39, 0.76, unit_key="USD/shares"),
                "CommonStockSharesOutstanding": {
                    "units": {
                        "shares": [
                            {"end": "2025-04-27", "val": 24300000000, "accn": "prior-accn", "filed": "2025-05-01"},
                            {"end": "2026-04-26", "val": 24200000000, "accn": TARGET_ACCN, "filed": "2026-05-20"},
                        ]
                    }
                },
            }
        }
    }


def _filing() -> Filing:
    return Filing(
        cik="1045810", accession_no=TARGET_ACCN, form="10-Q", filed_date="2026-05-20",
        primary_document="nvda-20260426.htm", ticker="NVDA",
    )


class FakeEdgar:
    async def get_companyfacts(self, cik):
        return _companyfacts()


def test_matches_periodic_forms():
    assert _matches(_filing())
    f = _filing()
    from dataclasses import replace
    assert _matches(replace(f, form="10-K"))
    assert not _matches(replace(f, form="8-K"))


def test_pick_value_selects_current_period_not_prior_year():
    val = _pick_value(_companyfacts(), [("us-gaap", "Revenues")], "USD", TARGET_ACCN)
    assert val == 81615000000


@pytest.mark.asyncio
async def test_render_combines_revenue_net_income_eps_and_shares():
    result = await _render(_filing(), FakeEdgar())
    assert result is not None
    assert "Revenue: $81.61B" in result.text
    assert "Net income: $58.32B" in result.text
    assert "2.40 basic" in result.text
    assert "2.39 diluted" in result.text
    assert "Shares outstanding: 24,200,000,000" in result.text


@pytest.mark.asyncio
async def test_render_returns_none_when_nothing_extractable():
    class EmptyEdgar:
        async def get_companyfacts(self, cik):
            return {"facts": {}}

    result = await _render(_filing(), EmptyEdgar())
    assert result is None
