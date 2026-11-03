"""Liverpool provider motor implementation."""

from __future__ import annotations

from typing import Any

from shared.scraping.motor import Motor

from . import parser as lv_parser


class Liverpool(Motor):
    """Liverpool scraping motor supporting Next.js RSC and legacy payloads."""

    PROVIDER_KEY = "lv"

    def __init__(self, job_id: str, url: str, *, storage_path: str) -> None:
        super().__init__(job_id, url, storage_path=storage_path)

    def scrape_page(self, body: dict[str, Any]) -> tuple[list[dict[str, Any]], str | None]:
        """Parse a Liverpool listing page into product records and pagination state.

        Args:
            body: Mapping with ``content`` containing the fetched HTML and ``url``
                containing the current page URL.

        Returns:
            A tuple of ``(items, next_url)``. Each item includes ``identifier``,
            ``title``, ``price``, and ``url``. ``next_url`` is ``None`` when no
            additional pages remain.
        """
        result = lv_parser.parse_listing_page(
            body.get("content", ""),
            body.get("url", self.url),
            job_id=self.job_id,
        )
        if result.incomplete:
            self._scrape_incomplete = True
            return [], None

        return result.items, result.next_url
