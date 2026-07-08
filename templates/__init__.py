"""Plugin registry for standardized filing templates.

Each template registers a cheap metadata-only `matches` predicate and an
async `render` function. `render` returns None to signal "extraction failed,
fall back to generic" -- see classifier.classify_and_render for the dispatch
contract. Adding a new standardized form type later means: new file in this
package + one `register()` call, no changes elsewhere.
"""
from dataclasses import dataclass
from typing import Awaitable, Callable

from models import Filing, TemplateResult

MatchFn = Callable[[Filing], bool]
RenderFn = Callable[[Filing, "edgar_client.EdgarClient"], Awaitable[TemplateResult | None]]


@dataclass(frozen=True)
class FilingTemplate:
    name: str
    matches: MatchFn
    render: RenderFn


REGISTRY: list[FilingTemplate] = []


def register(template: FilingTemplate) -> None:
    REGISTRY.append(template)


# Import side-effects populate REGISTRY. Add future templates (Schedule 13D/13G, 497/424B3 NAV --
# both still generic+AI, no reliable structured data source found for them) as additional
# imports here. Order doesn't matter for correctness: each template's `matches` predicate
# targets a disjoint set of forms (see each module's docstring), so at most one ever matches
# a given filing.
from . import share_issuance  # noqa: E402,F401
from . import financial_highlights  # noqa: E402,F401
from . import insider_forms  # noqa: E402,F401
from . import registration_fee  # noqa: E402,F401
