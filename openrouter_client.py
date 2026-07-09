"""On-demand AI summarization via OpenRouter -- SEC filing text, and RoboStrategy portfolio diffs."""
import html
import re

import httpx

import config

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# SEC filing documents are HTML/XHTML; fetch_filing_text() returns raw markup, so it's cleaned
# here (not in edgar_client.py -- other callers of fetch_filing_text, e.g. templates/insider_forms.py
# and templates/registration_fee.py, need the raw XML/HTML intact to parse it).
_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")
CLEAN_TEXT_MAX_CHARS = 15_000

_SYSTEM_PROMPT = (
    "You are summarizing an SEC filing for a retail investor. Be concise (under "
    "150 words), plain-English, and highlight anything financially or "
    "operationally material. Do not restate boilerplate legal language."
)

_ROBOSTRATEGY_SYSTEM_PROMPT = (
    "You are turning a factual list of portfolio changes into a short, readable paragraph for a "
    "retail investor. The list you're given is already the complete set of facts -- do not add "
    "any new facts, opinions, predictions, or investment implications beyond what's given. Just "
    "make the given facts read naturally, in plain English, under 120 words."
)


def _clean_filing_text(raw: str, max_chars: int = CLEAN_TEXT_MAX_CHARS) -> str:
    text = _TAG_RE.sub(" ", raw)
    text = html.unescape(text)
    text = _WHITESPACE_RE.sub(" ", text).strip()
    return text[:max_chars]


async def _chat_completion(system_prompt: str, user_prompt: str) -> str:
    api_key = config.get_openrouter_api_key()
    model = config.get_openrouter_model()

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            OPENROUTER_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            },
        )
        resp.raise_for_status()
        data = resp.json()

    return data["choices"][0]["message"]["content"].strip()


async def summarize(filing_text: str, form_type: str, ticker: str) -> str:
    cleaned_text = _clean_filing_text(filing_text)
    user_prompt = (
        f"Ticker: {ticker}\nForm type: {form_type}\n\n"
        f"Filing text (HTML stripped, may be truncated):\n\n{cleaned_text}"
    )
    return await _chat_completion(_SYSTEM_PROMPT, user_prompt)


async def narrate_robostrategy_update(diff_text: str) -> str:
    user_prompt = f"Portfolio changes:\n\n{diff_text}"
    return await _chat_completion(_ROBOSTRATEGY_SYSTEM_PROMPT, user_prompt)
