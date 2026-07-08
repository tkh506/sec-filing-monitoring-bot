"""Async SEC EDGAR client: ticker->CIK resolution, submissions, XBRL companyfacts.

A single shared, module-level rate limiter throttles every outbound request
(app-wide, not per polling cycle) to stay comfortably under SEC's ~10 req/sec
limit.
"""
import asyncio
import time

import httpx

COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik10}.json"
COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik10}.json"

MAX_REQ_PER_SEC = 8


class EdgarFetchError(Exception):
    pass


class RateLimiter:
    def __init__(self, max_per_sec: float = MAX_REQ_PER_SEC):
        self._interval = 1.0 / max_per_sec
        self._lock = asyncio.Lock()
        self._last = 0.0

    async def wait(self) -> None:
        async with self._lock:
            now = time.monotonic()
            delta = now - self._last
            if delta < self._interval:
                await asyncio.sleep(self._interval - delta)
            self._last = time.monotonic()


def normalize_cik(cik: str | int) -> str:
    """Zero-pad to 10 digits, as required by the data.sec.gov URL scheme."""
    return str(cik).zfill(10)


def build_document_url(cik: str | int, accession_no: str, filename: str) -> str:
    """URL for any document (or index.json) inside a filing's accession directory."""
    accn_nodash = accession_no.replace("-", "")
    return f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accn_nodash}/{filename}"


class EdgarClient:
    def __init__(self, user_agent: str):
        self._headers = {"User-Agent": user_agent}
        self._client = httpx.AsyncClient(headers=self._headers, timeout=15.0)
        self._limiter = RateLimiter()

    async def close(self) -> None:
        await self._client.aclose()

    async def _get_json(self, url: str) -> dict:
        await self._limiter.wait()
        try:
            resp = await self._client.get(url)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError as e:
            raise EdgarFetchError(f"GET {url} failed: {e}") from e

    async def get_company_tickers(self) -> dict:
        """Raw {"0": {"cik_str": ..., "ticker": ..., "title": ...}, ...} mapping."""
        return await self._get_json(COMPANY_TICKERS_URL)

    async def resolve_ticker(self, ticker: str) -> tuple[str, str] | None:
        """Look up (zero-padded CIK, company name) for a ticker, or None if unknown."""
        data = await self.get_company_tickers()
        ticker_upper = ticker.upper()
        for entry in data.values():
            if entry.get("ticker", "").upper() == ticker_upper:
                return normalize_cik(entry["cik_str"]), entry.get("title", "")
        return None

    async def get_submissions(self, cik: str) -> dict:
        url = SUBMISSIONS_URL.format(cik10=normalize_cik(cik))
        return await self._get_json(url)

    async def get_companyfacts(self, cik: str) -> dict:
        url = COMPANYFACTS_URL.format(cik10=normalize_cik(cik))
        return await self._get_json(url)

    async def get_filing_index(self, cik: str, accession_no: str) -> dict:
        """Directory listing of every document in a filing's accession -- needed to find
        exhibits (e.g. the S-8 fee-table XBRL) that aren't the submissions API's primaryDocument."""
        url = build_document_url(cik, accession_no, "index.json")
        return await self._get_json(url)

    async def fetch_filing_text(self, url: str, max_chars: int = 40000) -> str:
        """Fetch a filing document as text, truncated for downstream LLM use."""
        await self._limiter.wait()
        try:
            resp = await self._client.get(url)
            resp.raise_for_status()
        except httpx.HTTPError as e:
            raise EdgarFetchError(f"GET {url} failed: {e}") from e
        return resp.text[:max_chars]


def parse_recent_filings(cik: str, submissions: dict) -> list["Filing"]:
    """Parse the `filings.recent` parallel-array block into Filing objects,
    newest-first (matching EDGAR's own ordering)."""
    from models import Filing

    recent = submissions.get("filings", {}).get("recent", {})
    accession_numbers = recent.get("accessionNumber", [])
    forms = recent.get("form", [])
    filing_dates = recent.get("filingDate", [])
    primary_docs = recent.get("primaryDocument", [])
    items_list = recent.get("items", [])

    filings = []
    for i in range(len(accession_numbers)):
        items_raw = items_list[i] if i < len(items_list) else ""
        items = tuple(x.strip() for x in items_raw.split(",") if x.strip())
        filings.append(
            Filing(
                cik=normalize_cik(cik),
                accession_no=accession_numbers[i],
                form=forms[i] if i < len(forms) else "",
                filed_date=filing_dates[i] if i < len(filing_dates) else "",
                primary_document=primary_docs[i] if i < len(primary_docs) else "",
                items=items,
            )
        )
    return filings
