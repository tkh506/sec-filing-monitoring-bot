"""Aligned-clock scheduling: one cron job per check-frequency bucket.

Standalone AsyncIOScheduler (not python-telegram-bot's JobQueue wrapper) so
we control APScheduler directly -- CronTrigger with an IANA timezone computes
fire times in that zone, handling DST transitions correctly without any
hand-rolled boundary math. In-memory job store (the default) is intentional:
on restart we just resume from "now," relying on poller.py's accession-number
checkpoint diff to self-heal any missed boundaries rather than replaying them.
"""
import logging
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from poller import run_check_cycle

logger = logging.getLogger(__name__)

FREQUENCIES = (1, 2, 3, 6, 12, 24)
ET = ZoneInfo("America/New_York")


def build_scheduler(edgar, bot) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=ET)
    for hours in FREQUENCIES:
        # Cron's hour field only spans 0-23, so "*/24" (step >= range) is
        # invalid -- 24h just means "once a day, at midnight."
        hour_expr = "0" if hours == 24 else f"*/{hours}"
        scheduler.add_job(
            run_check_cycle,
            trigger=CronTrigger(hour=hour_expr, minute=0, timezone=ET),
            args=[hours, edgar, bot],
            id=f"check_cycle_{hours}h",
            max_instances=1,
            misfire_grace_time=300,
            coalesce=True,
        )
        logger.info("Registered check cycle job for frequency=%dh", hours)
    return scheduler
