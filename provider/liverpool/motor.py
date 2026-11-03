"""Liverpool provider motor implementation."""

from __future__ import annotations

from shared.scraping.motor import Motor
from shared.scraping.page_strategy import PageScrapeStrategy

from .parser import LiverpoolListingPageStrategy


class Liverpool(Motor):
    """Liverpool scraping motor supporting Next.js RSC and legacy payloads."""

    PROVIDER_KEY = "lv"
    RETRYABLE_STATUS_CODES = (404,)
    PAGE_STRATEGY = LiverpoolListingPageStrategy()

    def __init__(
        self,
        job_id: str,
        url: str,
        *,
        storage_path: str,
        page_strategy: PageScrapeStrategy | None = None,
    ) -> None:
        super().__init__(
            job_id,
            url,
            storage_path=storage_path,
            page_strategy=page_strategy or self.PAGE_STRATEGY,
        )
