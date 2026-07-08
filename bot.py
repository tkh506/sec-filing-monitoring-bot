"""Entrypoint: wire up the Telegram Application, handlers, and the EDGAR poll scheduler."""
import logging

from telegram import BotCommand
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, MessageHandler, filters

import config
import db
from edgar_client import EdgarClient
from handlers.callbacks import on_callback_query
from handlers.commands import (
    frequency,
    help_command,
    list_watchlist,
    on_text_message,
    recent,
    start,
    unwatch,
    watch,
)
from scheduler import build_scheduler

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

BOT_COMMANDS = [
    BotCommand("start", "Show the main menu"),
    BotCommand("watch", "Watch a ticker, e.g. /watch NVDA"),
    BotCommand("unwatch", "Stop watching a ticker, e.g. /unwatch NVDA"),
    BotCommand("list", "Show your watchlist"),
    BotCommand("frequency", "Set check frequency, e.g. /frequency NVDA 6h"),
    BotCommand("recent", "Show latest 5 filings for a ticker, e.g. /recent NVDA"),
    BotCommand("help", "Show help"),
]


async def _on_startup(application: Application) -> None:
    db.prune_old_pending_summaries()
    await application.bot.set_my_commands(BOT_COMMANDS)
    edgar = application.bot_data["edgar"]
    scheduler = build_scheduler(edgar, application.bot)
    scheduler.start()
    application.bot_data["scheduler"] = scheduler
    logger.info("Scheduler started.")


async def _on_shutdown(application: Application) -> None:
    scheduler = application.bot_data.get("scheduler")
    if scheduler is not None:
        scheduler.shutdown(wait=False)
    edgar = application.bot_data.get("edgar")
    if edgar is not None:
        await edgar.close()


def main() -> None:
    token = config.get_telegram_token()
    edgar = EdgarClient(config.get_edgar_user_agent())

    application = (
        Application.builder()
        .token(token)
        .post_init(_on_startup)
        .post_shutdown(_on_shutdown)
        .build()
    )
    application.bot_data["edgar"] = edgar

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("watch", watch))
    application.add_handler(CommandHandler("unwatch", unwatch))
    application.add_handler(CommandHandler("list", list_watchlist))
    application.add_handler(CommandHandler("frequency", frequency))
    application.add_handler(CommandHandler("recent", recent))
    application.add_handler(CallbackQueryHandler(on_callback_query))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text_message))

    logger.info("Starting bot (polling)...")
    application.run_polling()


if __name__ == "__main__":
    main()
