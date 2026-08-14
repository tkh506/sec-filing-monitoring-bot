"""Shared helper for sending Telegram messages with basic failure handling.

Used by both the poller (filing alerts) and the callback handler (AI
summaries) so retry/blocked-user/network-error handling lives in one place.
"""
import logging

from telegram.error import Forbidden, RetryAfter, TelegramError

logger = logging.getLogger(__name__)

# Telegram's real cap is 4096 UTF-16 code units per message; stay comfortably under that.
TELEGRAM_MESSAGE_LIMIT = 4000


def split_for_telegram(text: str, limit: int = TELEGRAM_MESSAGE_LIMIT) -> list[str]:
    """Splits text into <=limit-character chunks for Telegram's per-message length cap.

    Prefers breaking on a paragraph or line boundary over a mid-sentence cut; only forces a hard
    cut at `limit` if no such boundary exists within the current chunk (e.g. one very long
    unbroken paragraph).
    """
    if len(text) <= limit:
        return [text]

    chunks = []
    remaining = text
    while len(remaining) > limit:
        split_at = remaining.rfind("\n\n", 0, limit)
        if split_at == -1:
            split_at = remaining.rfind("\n", 0, limit)
        if split_at == -1:
            split_at = remaining.rfind(" ", 0, limit)
        if split_at == -1:
            split_at = limit
        chunks.append(remaining[:split_at].rstrip())
        remaining = remaining[split_at:].lstrip()
    if remaining:
        chunks.append(remaining)
    return chunks


async def send_with_retry(bot, chat_id: int, text: str, **kwargs) -> bool:
    """Best-effort send. Returns True on success, False on any failure.

    Never raises -- a failed send for one user must not abort processing of
    other users in the same fan-out loop.
    """
    try:
        await bot.send_message(chat_id=chat_id, text=text, **kwargs)
        return True
    except RetryAfter as e:
        logger.warning("Telegram flood control, retrying after %.1fs", e.retry_after)
        try:
            import asyncio

            await asyncio.sleep(e.retry_after)
            await bot.send_message(chat_id=chat_id, text=text, **kwargs)
            return True
        except TelegramError:
            logger.exception("Retry after flood control failed for chat_id=%s", chat_id)
            return False
    except Forbidden:
        logger.info("User %s has blocked the bot; skipping.", chat_id)
        return False
    except TelegramError:
        logger.exception("Failed to send message to chat_id=%s", chat_id)
        return False
