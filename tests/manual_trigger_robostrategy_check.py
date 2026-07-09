"""One-off script to test the RoboStrategy alert pipeline end-to-end WITHOUT waiting for a real
change on the live page. Run this on the same machine/database as the deployed bot (so it sees
real subscribers and writes to the same data/bot.db the running service uses):

    .venv/bin/python tests/manual_trigger_robostrategy_check.py

It fetches the real current portfolio page, fabricates a slightly different "previous" snapshot
(tweaks the first holding's fair value/%, drops the last holding, nudges NAV per share -- so
added/removed/changed logic all get exercised in one pass), saves that as the last-seen state,
then immediately runs the real check cycle via a real telegram.Bot. This WILL send real Telegram
messages to every subscriber who has RoboStrategy alerts turned on.

Safe to run repeatedly: it always re-derives the fake "previous" snapshot from whatever the live
page currently looks like, and the real check cycle overwrites the stored snapshot with the real
current data afterward -- the next natural 3h check just continues normally from there. Running it
twice in a row will show a real message on the first run and nothing on the second (since nothing
actually changed between those two runs), which is a good way to confirm the "no duplicate alerts"
behavior too.
"""
import asyncio
import json
import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402
import db  # noqa: E402
from robostrategy_client import fetch_portfolio_html, parse_portfolio  # noqa: E402
from robostrategy_monitor import _holdings_to_dicts, run_robostrategy_check  # noqa: E402
from telegram import Bot  # noqa: E402


async def main() -> None:
    subscribers = db.get_robostrategy_subscribers()
    if not subscribers:
        print(
            "No one has RoboStrategy alerts turned on -- toggle it on in Telegram first "
            "(tap the button, or /robostrategy), then re-run this script."
        )
        return
    print(f"Subscribers who will receive a test alert: {subscribers}")

    user_agent = config.get_edgar_user_agent()
    page_html = await fetch_portfolio_html(user_agent)
    current = parse_portfolio(page_html)

    if len(current.holdings) < 2:
        print("Not enough holdings on the live page to fabricate a realistic test diff.")
        return

    # Fabricate a "previous" snapshot that differs from the real current one in all three ways
    # the feature tracks: a fair-value/% change (first holding), a removed holding (drop the
    # last one -- it'll show up as "added" when we diff against the real current data), and a
    # NAV-per-share change.
    tweaked_first = replace(
        current.holdings[0],
        fair_value=round(current.holdings[0].fair_value * 0.9),
        pct_nav=round(current.holdings[0].pct_nav * 0.9, 1),
    )
    fake_previous_holdings = (tweaked_first,) + current.holdings[1:-1]
    fake_previous_nav = round(current.nav_per_share * 0.95, 2) if current.nav_per_share else None

    db.save_robostrategy_snapshot(
        current.as_of, fake_previous_nav, json.dumps(_holdings_to_dicts(fake_previous_holdings))
    )
    print("Fabricated a fake 'previous' snapshot and saved it as the last-seen state.")
    print(f"  (dropped holding, so it'll show as newly added: {current.holdings[-1].name!r})")

    bot = Bot(token=config.get_telegram_token())
    print("Running the real check cycle now -- this WILL send real Telegram messages.")
    await run_robostrategy_check(bot, user_agent)
    print("Done. Check Telegram.")


if __name__ == "__main__":
    asyncio.run(main())
