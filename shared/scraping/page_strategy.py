"""Strategy contracts and result value objects for scraping listing pages.

Providers implement :class:`PageScrapeStrategy` to parse a single fetched HTML
document into a :class:`PageScrapeResult`. Providers that support multiple
page layouts (for example, server-rendered DOM vs. embedded JSON state, or
Next.js App Router RSC chunks vs. legacy ``__NEXT_DATA__``) can compose
multiple strategies via :class:`FallbackPageScrapeStrategy`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, Sequence, runtime_checkable


@dataclass(frozen=True)
class PageScrapeResult:
    """Normalized result produced by a page-scraping strategy.

    Args:
        items: Extracted product dictionaries with ``identifier``, ``title``,
            ``price``, and ``url``.
        next_url: URL of the next page when pagination continues, or ``None``.
        blocked_reason: Machine-readable reason when anti-bot or login gating
            was detected on the page.
        incomplete_reason: Machine-readable reason when the expected results
            container or payload was missing.
        incomplete: Boolean flag indicating the page could not be parsed
            completely and missing-item reconciliation must be skipped.
    """

    items: list[dict[str, Any]]
    next_url: str | None = None
    blocked_reason: str | None = None
    incomplete_reason: str | None = None
    incomplete: bool = False

    @property
    def is_incomplete(self) -> bool:
        """Return ``True`` when the page failed completeness or block checks."""
        return bool(self.incomplete or self.blocked_reason or self.incomplete_reason)


@runtime_checkable
class PageScrapeStrategy(Protocol):
    """Strategy contract for extracting items and pagination from a page."""

    def parse_page(
        self,
        content: str,
        url: str,
        *,
        job_id: str = "",
    ) -> PageScrapeResult:
        """Parse fetched page ``content`` from ``url`` into a :class:`PageScrapeResult`."""
        ...


class FallbackPageScrapeStrategy:
    """Composite strategy that tries child page strategies in order until one succeeds.

    If any strategy detects an explicit ``blocked_reason``, evaluation stops
    immediately and returns that blocked result. Otherwise, the first strategy
    that extracts at least one item wins. If no strategy produces items, an
    incomplete :class:`PageScrapeResult` is returned.
    """

    def __init__(
        self,
        strategies: Sequence[PageScrapeStrategy],
        *,
        empty_incomplete_reason: str | None = None,
    ) -> None:
        if not strategies:
            raise ValueError("FallbackPageScrapeStrategy requires at least one strategy.")
        self.strategies: tuple[PageScrapeStrategy, ...] = tuple(strategies)
        self.empty_incomplete_reason = empty_incomplete_reason

    def parse_page(
        self,
        content: str,
        url: str,
        *,
        job_id: str = "",
    ) -> PageScrapeResult:
        """Try each configured strategy in sequence until items or a block are found."""
        last_result: PageScrapeResult | None = None
        for strategy in self.strategies:
            result = strategy.parse_page(content, url, job_id=job_id)
            if result.blocked_reason:
                return result
            if result.items:
                return result
            last_result = result

        incomplete_reason = self.empty_incomplete_reason or (
            last_result.incomplete_reason if last_result is not None else None
        )
        return PageScrapeResult(
            items=[],
            next_url=None,
            incomplete_reason=incomplete_reason,
            incomplete=True,
        )
