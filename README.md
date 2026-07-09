# SEC Filing Monitor — Telegram Bot

A Telegram bot that watches SEC EDGAR for new filings on tickers you choose and alerts you the
moment one is filed — no more refreshing EDGAR by hand.

## Features
- Watch up to 5 US-listed tickers, each on its own check schedule (1h–24h).
- Interactive menu (`/start`) — add/remove tickers and change frequency with buttons, no need to
  remember command syntax.
- Standardized, AI-free summaries for share issuances, 10-Q/10-K financial highlights, insider
  transactions (Form 3/4/5), and S-8 registration filings — parsed straight from SEC's own
  structured data, no token cost.
- Everything else arrives with a one-tap "🤖 Summarize with AI" button (also available as an
  optional extra on the standardized alerts).
- Bonus: optional alerts for changes to a public fund's portfolio page (holdings, valuations, NAV
  per share) — toggle on/off with one button.
- Open to anyone — no account or allowlist required, just start the bot on Telegram.

## Stack
Python, `python-telegram-bot`, SQLite, SEC EDGAR's public JSON APIs, OpenRouter for on-demand
summarization.
