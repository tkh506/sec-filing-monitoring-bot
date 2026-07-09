"""Standalone script exercising the RoboStrategy client against the LIVE portfolio page. Run
manually after filling in .env:

    python tests/manual_validation_robostrategy.py

Requires SEC_EDGAR_USER_AGENT to be set (reused here as a general polite-scraping identity
string); does not touch Telegram or OpenRouter.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402
from robostrategy_client import fetch_portfolio_html, parse_portfolio  # noqa: E402


async def main() -> None:
    page_html = await fetch_portfolio_html(config.get_edgar_user_agent())
    snapshot = parse_portfolio(page_html)

    print(f"As of: {snapshot.as_of}")
    print(f"NAV per share: {snapshot.nav_per_share}")
    print(f"{len(snapshot.holdings)} holdings:")
    total_pct = 0.0
    for h in snapshot.holdings:
        print(f"  {h.name:30s} {h.business:28s} ${h.fair_value:>14,.0f}  {h.pct_nav:>5.1f}%")
        total_pct += h.pct_nav
    print(f"Total % of NAV across holdings: {total_pct:.1f}%")


if __name__ == "__main__":
    asyncio.run(main())
