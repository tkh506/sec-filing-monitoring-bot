"""Inline-keyboard builders for the button-driven menu."""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

import db

HELP_TEXT = (
    "<b>SEC Filing Monitor</b>\n\n"
    "I watch SEC EDGAR for new filings on tickers you choose and alert you here as soon as "
    "one is filed.\n\n"
    "• Watch up to 5 tickers at once\n"
    "• Set a check frequency per ticker: 1h, 2h, 3h, 6h, 12h, or 24h\n"
    "• Share-issuance filings get a pre-formatted summary automatically\n"
    "• Everything else comes with a 🤖 Summarize with AI button\n"
    "• Look up any ticker's latest 5 filings on demand, any time\n\n"
    "Use the buttons below, or type these commands:\n"
    "/watch TICKER — add a ticker\n"
    "/unwatch TICKER — remove a ticker\n"
    "/list — show your watchlist\n"
    "/frequency TICKER 6h — change check frequency\n"
    "/recent TICKER — show the latest 5 filings right now"
)


def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📋 My Watchlist", callback_data="menu:list")],
            [InlineKeyboardButton("➕ Add Ticker", callback_data="menu:add")],
            [InlineKeyboardButton("🔎 Recent Filings", callback_data="menu:recent")],
            [InlineKeyboardButton("❓ Help", callback_data="menu:help")],
        ]
    )


def post_watch_menu(ticker: str) -> InlineKeyboardMarkup:
    """Shown right after successfully adding a ticker, so the next likely action (setting a
    non-default frequency) is one tap away instead of a trip through My Watchlist."""
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("⏱ Set Frequency", callback_data=f"freq:{ticker}")],
            [InlineKeyboardButton("« Main Menu", callback_data="menu:main")],
        ]
    )


def watchlist_menu(user_id: int) -> tuple[str, InlineKeyboardMarkup]:
    entries = db.get_watchlist_for_user(user_id)
    keyboard = []
    if not entries:
        text = "You're not watching any tickers yet."
    else:
        lines = [f"• {e.ticker} — every {e.frequency_hours}h" for e in entries]
        text = "Your watchlist:\n" + "\n".join(lines)
        for e in entries:
            keyboard.append(
                [
                    InlineKeyboardButton(f"⏱ {e.ticker}", callback_data=f"freq:{e.ticker}"),
                    InlineKeyboardButton(f"🗑 {e.ticker}", callback_data=f"unwatch:{e.ticker}"),
                ]
            )
    keyboard.append([InlineKeyboardButton("➕ Add Ticker", callback_data="menu:add")])
    keyboard.append([InlineKeyboardButton("« Back", callback_data="menu:main")])
    return text, InlineKeyboardMarkup(keyboard)


def frequency_menu(ticker: str) -> InlineKeyboardMarkup:
    rows = []
    row = []
    for hours in db.VALID_FREQUENCIES:
        row.append(InlineKeyboardButton(f"{hours}h", callback_data=f"setfreq:{ticker}:{hours}"))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton("« Back", callback_data="menu:list")])
    return InlineKeyboardMarkup(rows)


def unwatch_confirm_menu(ticker: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Yes, unwatch", callback_data=f"unwyes:{ticker}"),
                InlineKeyboardButton("❌ Cancel", callback_data=f"unwno:{ticker}"),
            ]
        ]
    )
