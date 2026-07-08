"""Shared helper for sending Telegram messages with basic failure handling.

Used by both the poller (filing alerts) and the callback handler (AI
summaries) so retry/blocked-user/network-error handling lives in one place.
"""
import logging

from telegram.error import Forbidden, RetryAfter, TelegramError

logger = logging.getLogger(__name__)


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
