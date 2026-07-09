"""One-off script to test the RoboStrategy alert pipeline end-to-end WITHOUT waiting for a real
change on the live page. Run this on the same machine/database as the deployed bot (so it sees
real subscribers and writes to the same data/bot.db the running service uses):

    .venv/bin/python tests/manual_trigger_robostrategy_check.py            # fabricate a diff + check
    .venv/bin/python tests/manual_trigger_robostrategy_check.py --check-only  # just run a real check,
                                                                              # no fabrication

Default mode fetches the real current portfolio page, fabricates a slightly different "previous"
snapshot (tweaks the first holding's fair value/%, drops the last holding, nudges NAV per share --
so added/removed/changed logic all get exercised in one pass), saves that as the last-seen state,
then immediately runs the real check cycle via a real telegram.Bot. This WILL send real Telegram
messages to every subscriber who has RoboStrategy alerts turned on.

IMPORTANT: default mode fabricates a FRESH fake diff every time it runs, so running it twice in a
row sends the SAME alert twice -- it does not "settle" to silence on a second run, because each
run manufactures its own diff from scratch and overwrites whatever the previous run's real check
cycle had just saved. To see the silent/no-change behavior, run once in default mode, then run
again with `--check-only`: that second invocation performs a real check against the snapshot the
first run actually saved (the real current data), so it should produce no message at all.
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
    check_only = "--check-only" in sys.argv

    subscribers = db.get_robostrategy_subscribers()
    if not subscribers:
        print(
            "No one has RoboStrategy alerts turned on -- toggle it on in Telegram first "
            "(tap the button, or /robostrategy), then re-run this script."
        )
        return
    print(f"Subscribers who will receive a test alert: {subscribers}")

    user_agent = config.get_edgar_user_agent()

    if not check_only:
        page_html = await fetch_portfolio_html(user_agent)
        current = parse_portfolio(page_html)

        if len(current.holdings) < 2:
            print("Not enough holdings on the live page to fabricate a realistic test diff.")
            return

        # Fabricate a "previous" snapshot that differs from the real current one in all three
        # ways the feature tracks: a fair-value/% change (first holding), a removed holding
        # (drop the last one -- it'll show up as "added" when we diff against real current
        # data), and a NAV-per-share change.
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
    else:
        print("--check-only: running a real check against whatever is already saved as last-seen "
              "(no fabrication) -- expect no message if nothing has actually changed.")

    bot = Bot(token=config.get_telegram_token())
    print("Running the real check cycle now -- this WILL send real Telegram messages if there's a diff.")
    await run_robostrategy_check(bot, user_agent)
    print("Done. Check Telegram (silence is expected in --check-only mode if nothing changed).")


if __name__ == "__main__":
    asyncio.run(main())
