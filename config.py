"""Environment-variable configuration.

Every accessor below is a plain function evaluated lazily at first use. Nothing
at module import time reads a required env var, so `import config` never
raises -- a missing/placeholder .env only breaks the specific feature that
needed it, with an actionable error message.
"""
import os

from dotenv import load_dotenv

load_dotenv()

_PLACEHOLDER_PREFIXES = ("YOUR_",)


class ConfigError(RuntimeError):
    pass


def _get_required(key: str) -> str:
    val = os.environ.get(key, "").strip()
    if not val or val.startswith(_PLACEHOLDER_PREFIXES):
        raise ConfigError(
            f"{key} is not set. Copy .env.example to .env and fill in a real value."
        )
    return val


def get_telegram_token() -> str:
    return _get_required("TELEGRAM_BOT_TOKEN")


def get_openrouter_api_key() -> str:
    return _get_required("OPENROUTER_API_KEY")


def get_openrouter_model() -> str:
    return os.environ.get("OPENROUTER_MODEL", "anthropic/claude-sonnet-4.5").strip()


def get_edgar_user_agent() -> str:
    return _get_required("SEC_EDGAR_USER_AGENT")


def get_database_path() -> str:
    return os.environ.get("DATABASE_PATH", "data/bot.db").strip()
