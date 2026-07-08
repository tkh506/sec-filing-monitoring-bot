"""Fallback formatter for any filing that isn't (or fails) a standardized template."""
from models import Filing, TemplateResult


async def render_generic(filing: Filing) -> TemplateResult:
    text = (
        f"📄 <b>[{filing.ticker}]</b> {filing.form} filing\n"
        f"Filed: {filing.filed_date}\n"
        f"<a href=\"{filing.filing_index_url}\">View filing</a>"
    )
    return TemplateResult(text=text)
