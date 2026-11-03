"""Amazon Mexico scraper motor."""

from __future__ import annotations

from shared.scraping.motor import Motor
from shared.scraping.page_strategy import PageScrapeStrategy

from .parser import DEFAULT_DOMAIN, AmazonSearchPageStrategy


class Amazon(Motor):
    """Scrape Amazon Mexico search result pages."""

    PROVIDER_KEY = "az"
    DOMAIN = DEFAULT_DOMAIN
    PAGE_STRATEGY = AmazonSearchPageStrategy(domain=DEFAULT_DOMAIN)

    def __init__(
        self,
        job_id: str,
        url: str,
        *,
        storage_path: str,
        page_strategy: PageScrapeStrategy | None = None,
    ) -> None:
        """Create an Amazon motor for a generated or explicit result URL."""
        strategy = page_strategy or AmazonSearchPageStrategy(domain=self.DOMAIN)
        super().__init__(
            job_id,
            url,
            storage_path=storage_path,
            page_strategy=strategy,
        )
