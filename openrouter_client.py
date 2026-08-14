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
# 15,000 was too tight -- a real 424B3 prospectus supplement cleaned to 23,383 chars, cutting off
# a fact (a Secretary appointment) that appeared past the old limit. 40,000 gives comfortable
# headroom over that example while staying well under the 150,000-char raw fetch budget's typical
# clean-text yield (see handlers/callbacks.py).
CLEAN_TEXT_MAX_CHARS = 40_000

_SYSTEM_PROMPT = (
    "You extract factual information from an SEC filing for a retail investor. Output a "
    "bullet-point list, one atomic fact per bullet -- filer name, form type and filing date, key "
    "figures (with their 'as of' dates), named parties and their roles, and any other concrete "
    "facts stated in the text. Use the exact figures, dates, and names as they appear.\n\n"
    "Report only what the filing text itself states. Do not add outside knowledge, your own "
    "analysis, opinions, predictions, or investment implications. Do not claim a figure "
    "increased, decreased, or changed unless the filing text itself makes that comparison -- a "
    "number appearing once is a fact on its own, not evidence of a trend.\n\n"
    "If the filing discloses risk factors, list them factually and attribute them to the filing "
    "(e.g. \"The filing discloses risk factors including...\") rather than presenting your own "
    "risk assessment or characterizing how significant they are.\n\n"
    "Skip boilerplate legal/procedural language not specific to this filing. Keep each bullet "
    "concise, but include as many bullets as needed to cover the material facts."
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
