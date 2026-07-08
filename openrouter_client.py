"""On-demand AI summarization of a filing document via OpenRouter."""
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
    "You extract factual information from SEC filings for a retail investor. Report only what "
    "the filing text itself states -- do not add your own analysis, opinions, predictions, or "
    "investment implications, and do not speculate beyond the text.\n\n"
    "If the filing explicitly discloses risks, uncertainties, or material impacts (e.g. in a "
    "Risk Factors section or similar), report those as stated -- that's factual content from the "
    "filing, not your opinion. But do not editorialize on how significant they are or what they "
    "might mean for the stock.\n\n"
    "Format as short factual bullet points: what happened, the key parties/numbers/dates involved, "
    "and any risks or material impacts explicitly disclosed in the text. Skip boilerplate "
    "legal/procedural language. Under 200 words."
)


def _clean_filing_text(raw: str, max_chars: int = CLEAN_TEXT_MAX_CHARS) -> str:
    text = _TAG_RE.sub(" ", raw)
    text = html.unescape(text)
    text = _WHITESPACE_RE.sub(" ", text).strip()
    return text[:max_chars]


async def summarize(filing_text: str, form_type: str, ticker: str) -> str:
    api_key = config.get_openrouter_api_key()
    model = config.get_openrouter_model()

    cleaned_text = _clean_filing_text(filing_text)
    user_prompt = (
        f"Ticker: {ticker}\nForm type: {form_type}\n\n"
        f"Filing text (HTML stripped, may be truncated):\n\n{cleaned_text}"
    )

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            OPENROUTER_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
            },
        )
        resp.raise_for_status()
        data = resp.json()

    return data["choices"][0]["message"]["content"].strip()
