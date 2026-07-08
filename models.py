"""Small immutable data carriers shared across modules."""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Filing:
    cik: str
    accession_no: str
    form: str
    filed_date: str  # ISO8601 date, e.g. "2024-08-01"
    primary_document: str
    items: tuple[str, ...] = field(default_factory=tuple)  # 8-K item numbers, e.g. ("3.02",)
    ticker: str = ""  # set per-subscriber by the poller before rendering

    @property
    def filing_index_url(self) -> str:
        """SEC EDGAR filing index page (accession dashes stripped for the path)."""
        accn_nodash = self.accession_no.replace("-", "")
        return (
            f"https://www.sec.gov/Archives/edgar/data/{int(self.cik)}/"
            f"{accn_nodash}/{self.primary_document}"
        )

    @property
    def raw_xml_url(self) -> str:
        """For ownership filings (Form 3/4/5), `primary_document` points at the XSL-rendered
        HTML viewer (e.g. "xslF345X06/wk-form4_....xml") -- fetching that URL returns rendered
        HTML, not parseable XML. The raw machine-readable XML lives at the accession root under
        just the filename, so strip any viewer subfolder."""
        accn_nodash = self.accession_no.replace("-", "")
        filename = self.primary_document.rsplit("/", 1)[-1]
        return f"https://www.sec.gov/Archives/edgar/data/{int(self.cik)}/{accn_nodash}/{filename}"


@dataclass(frozen=True)
class WatchlistEntry:
    id: int
    user_id: int
    ticker: str
    cik: str
    frequency_hours: int
    last_checked_at: str | None
    last_seen_accession_no: str | None


@dataclass(frozen=True)
class ShareIssuanceResult:
    new_shares_issued: int
    total_outstanding: int
    previous_outstanding: int
    pct_change: float


@dataclass(frozen=True)
class TemplateResult:
    text: str
    parse_mode: str = "HTML"
