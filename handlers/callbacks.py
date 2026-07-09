"""Single router for all inline-button taps: menu navigation + AI summarize."""
import logging

from telegram import Update
from telegram.ext import ContextTypes

import db
import openrouter_client
from handlers import actions, menu
from handlers.commands import AWAITING_TICKER_KEY

logger = logging.getLogger(__name__)


async def on_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    db.upsert_user(query.from_user.id)

    data = query.data or ""
    prefix, _, rest = data.partition(":")

    if prefix == "menu":
        await _handle_menu(query, context, rest)
    elif prefix == "freq":
        await query.edit_message_text(f"Set check frequency for {rest}:", reply_markup=menu.frequency_menu(rest))
    elif prefix == "setfreq":
        ticker, _, hours = rest.partition(":")
        reply = await actions.do_set_frequency(query.from_user.id, ticker, int(hours))
        text, markup = menu.watchlist_menu(query.from_user.id)
        await query.edit_message_text(f"{reply}\n\n{text}", reply_markup=markup)
    elif prefix == "unwatch":
        await query.edit_message_text(f"Unwatch {rest}?", reply_markup=menu.unwatch_confirm_menu(rest))
    elif prefix == "unwyes":
        reply = await actions.do_unwatch(query.from_user.id, rest)
        text, markup = menu.watchlist_menu(query.from_user.id)
        await query.edit_message_text(f"{reply}\n\n{text}", reply_markup=markup)
    elif prefix == "unwno":
        text, markup = menu.watchlist_menu(query.from_user.id)
        await query.edit_message_text(text, reply_markup=markup)
    elif prefix == "summarize":
        await _handle_summarize(query, context, rest)
    elif prefix == "robostrategy":
        await _handle_robostrategy_toggle(query, context)
    elif prefix == "rsai":
        await _handle_robostrategy_ai_take(query, context, rest)
    else:
        logger.warning("Unknown callback_data prefix: %r", data)


async def _handle_menu(query, context: ContextTypes.DEFAULT_TYPE, action: str) -> None:
    user_id = query.from_user.id
    if action == "main":
        context.user_data.pop(AWAITING_TICKER_KEY, None)
        await query.edit_message_text("What would you like to do?", reply_markup=menu.main_menu(user_id))
    elif action == "list":
        context.user_data.pop(AWAITING_TICKER_KEY, None)
        text, markup = menu.watchlist_menu(user_id)
        await query.edit_message_text(text, reply_markup=markup)
    elif action == "add":
        context.user_data[AWAITING_TICKER_KEY] = "watch"
        await query.edit_message_text("Send me the ticker symbol to watch (e.g. NVDA).")
    elif action == "recent":
        context.user_data[AWAITING_TICKER_KEY] = "recent"
        await query.edit_message_text("Send me the ticker to look up (e.g. NVDA) — I'll show its latest 5 filings.")
    elif action == "help":
        context.user_data.pop(AWAITING_TICKER_KEY, None)
        await query.edit_message_text(menu.HELP_TEXT, reply_markup=menu.main_menu(user_id), parse_mode="HTML")


async def _handle_robostrategy_toggle(query, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = query.from_user.id
    enabled = not db.is_robostrategy_enabled(user_id)
    db.set_robostrategy_enabled(user_id, enabled)
    status = "ON (checked every 3h)" if enabled else "OFF"
    await query.edit_message_text(
        f"RoboStrategy portfolio alerts turned {status}.", reply_markup=menu.main_menu(user_id)
    )


async def _handle_robostrategy_ai_take(query, context: ContextTypes.DEFAULT_TYPE, summary_id: str) -> None:
    pending = db.get_robostrategy_pending_ai(summary_id)
    if pending is None:
        await query.message.reply_text("This request expired.")
        return

    await query.edit_message_reply_markup(reply_markup=None)
    await query.message.reply_text("Writing an AI take…")

    try:
        narration = await openrouter_client.narrate_robostrategy_update(pending["diff_text"])
        await query.message.reply_text(f"📝 AI Take\n\n{narration}")
    except Exception:
        logger.exception("RoboStrategy AI take failed for summary_id=%s", summary_id)
        await query.message.reply_text("Sorry, the AI take failed. Try again later.")


async def _handle_summarize(query, context: ContextTypes.DEFAULT_TYPE, summary_id: str) -> None:
    pending = db.get_pending_summary(summary_id)
    if pending is None:
        await query.message.reply_text("This summarize request expired.")
        return

    await query.edit_message_reply_markup(reply_markup=None)
    await query.message.reply_text("Fetching and summarizing…")

    edgar = actions.get_edgar(context)
    try:
        # Fetch a larger raw HTML budget than the eventual clean-text size sent to the model --
        # openrouter_client strips tags/whitespace before truncating, and a lot of this raw
        # budget is markup that won't survive that cleanup.
        doc_text = await edgar.fetch_filing_text(pending["filing_url"], max_chars=150_000)
        summary = await openrouter_client.summarize(
            doc_text, form_type=pending["form_type"], ticker=pending["ticker"]
        )
        await query.message.reply_text(
            f"📝 AI Summary — {pending['ticker']} {pending['form_type']}\n\n{summary}"
        )
    except Exception:
        logger.exception("Summarize failed for summary_id=%s", summary_id)
        await query.message.reply_text("Sorry, summarization failed. Try again later.")
