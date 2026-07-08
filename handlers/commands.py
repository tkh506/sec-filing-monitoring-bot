"""Slash commands + the free-text ticker reply that follows an "awaiting ticker" button flow.

Open bot -- no allowlist, anyone who finds it on Telegram can use it.
"""
from functools import wraps

from telegram import Update
from telegram.ext import ContextTypes

import db
from handlers import actions, menu

# Value is the pending action ("watch" or "recent") once the user taps a button that needs a
# ticker typed next; absent/falsy means no flow is in progress.
AWAITING_TICKER_KEY = "awaiting_ticker"


def track_user(handler):
    """Records the user and clears any in-progress button flow before running a direct command."""

    @wraps(handler)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        db.upsert_user(update.effective_user.id)
        context.user_data.pop(AWAITING_TICKER_KEY, None)
        return await handler(update, context)

    return wrapper


@track_user
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "👋 Welcome to the SEC Filing Monitor bot. I'll alert you here when a ticker you "
        "watch files something new with the SEC.",
        reply_markup=menu.main_menu(),
    )


@track_user
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(menu.HELP_TEXT, reply_markup=menu.main_menu(), parse_mode="HTML")


@track_user
async def watch(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Usage: /watch TICKER")
        return
    reply, ticker = await actions.do_watch(update.effective_user.id, context.args[0], actions.get_edgar(context))
    markup = menu.post_watch_menu(ticker) if ticker else menu.main_menu()
    await update.message.reply_text(reply, reply_markup=markup)


@track_user
async def unwatch(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Usage: /unwatch TICKER")
        return
    reply = await actions.do_unwatch(update.effective_user.id, context.args[0])
    await update.message.reply_text(reply, reply_markup=menu.main_menu())


@track_user
async def list_watchlist(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text, markup = menu.watchlist_menu(update.effective_user.id)
    await update.message.reply_text(text, reply_markup=markup)


@track_user
async def frequency(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /frequency TICKER [1h|2h|3h|6h|12h|24h]")
        return
    ticker = context.args[0].upper()
    freq_str = context.args[1].lower().rstrip("h")
    if not freq_str.isdigit() or int(freq_str) not in db.VALID_FREQUENCIES:
        await update.message.reply_text("Frequency must be one of: 1h, 2h, 3h, 6h, 12h, 24h")
        return
    reply = await actions.do_set_frequency(update.effective_user.id, ticker, int(freq_str))
    await update.message.reply_text(reply, reply_markup=menu.main_menu())


@track_user
async def recent(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Usage: /recent TICKER")
        return
    error = await actions.do_show_recent(
        context.bot, update.effective_user.id, context.args[0], actions.get_edgar(context)
    )
    if error:
        await update.message.reply_text(error, reply_markup=menu.main_menu())


async def on_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the free-text ticker reply after the user taps "Add Ticker" or "Recent Filings"."""
    action = context.user_data.get(AWAITING_TICKER_KEY)
    if not action:
        return  # not in a flow -- ignore stray text
    context.user_data.pop(AWAITING_TICKER_KEY, None)
    db.upsert_user(update.effective_user.id)
    edgar = actions.get_edgar(context)

    if action == "watch":
        reply, ticker = await actions.do_watch(update.effective_user.id, update.message.text, edgar)
        markup = menu.post_watch_menu(ticker) if ticker else menu.main_menu()
        await update.message.reply_text(reply, reply_markup=markup)
    elif action == "recent":
        error = await actions.do_show_recent(context.bot, update.effective_user.id, update.message.text, edgar)
        if error:
            await update.message.reply_text(error, reply_markup=menu.main_menu())
