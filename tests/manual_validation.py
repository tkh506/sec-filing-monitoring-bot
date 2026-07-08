"""Standalone script exercising the EDGAR client and share-issuance extraction
against LIVE data for NVDA and DXYZ. Run manually after filling in .env:

    python tests/manual_validation.py

Requires SEC_EDGAR_USER_AGENT to be set; does not touch Telegram or OpenRouter.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402
from edgar_client import EdgarClient, parse_recent_filings  # noqa: E402
from templates.share_issuance import _matches, extract_share_issuance  # noqa: E402

TEST_TICKERS = ["NVDA", "DXYZ"]

_SHARE_CONCEPTS = [
    ("dei", "EntityCommonStockSharesOutstanding"),
    ("us-gaap", "CommonStockSharesOutstanding"),
    ("us-gaap", "CommonStockSharesIssued"),
]


async def main() -> None:
    edgar = EdgarClient(config.get_edgar_user_agent())
    try:
        for ticker in TEST_TICKERS:
            print(f"\n=== {ticker} ===")
            resolved = await edgar.resolve_ticker(ticker)
            if resolved is None:
                print(f"  Could not resolve CIK for {ticker}")
                continue
            cik, name = resolved
            print(f"  CIK={cik} name={name!r}")

            submissions = await edgar.get_submissions(cik)
            filings = parse_recent_filings(cik, submissions)
            print(f"  {len(filings)} recent filings, showing 5 newest:")
            for f in filings[:5]:
                print(f"    {f.filed_date}  {f.form:10s}  accn={f.accession_no}  items={f.items}")

            companyfacts = await edgar.get_companyfacts(cik)
            has_concept = any(
                companyfacts.get("facts", {}).get(tax, {}).get(concept)
                for tax, concept in _SHARE_CONCEPTS
            )
            print(f"  Has share-count XBRL concept: {has_concept}")

            candidate = next((f for f in filings if _matches(f)), None)
            if candidate is None:
                print("  No share-issuance-candidate filing in the recent window.")
                continue
            result = extract_share_issuance(companyfacts, candidate.accession_no, candidate.filed_date)
            print(
                f"  Candidate filing: {candidate.form} filed {candidate.filed_date} "
                f"(accn={candidate.accession_no})"
            )
            print(f"  Extraction result: {result}")
    finally:
        await edgar.close()


if __name__ == "__main__":
    asyncio.run(main())
