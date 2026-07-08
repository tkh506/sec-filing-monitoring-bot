"""Dispatch a filing to its standardized template, or fall back to generic."""
from models import Filing, TemplateResult
from templates import REGISTRY
from templates.generic import render_generic


async def classify_and_render(filing: Filing, edgar) -> tuple[TemplateResult, bool]:
    """Returns (result, is_standardized)."""
    for template in REGISTRY:
        if template.matches(filing):
            result = await template.render(filing, edgar)
            if result is not None:
                return result, True
            break  # matched but extraction failed -> fall through to generic
    return await render_generic(filing), False
