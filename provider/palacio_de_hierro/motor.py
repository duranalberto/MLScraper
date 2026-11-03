"""Palacio de Hierro provider motor implementation."""

from __future__ import annotations

from typing import List, Optional

from bs4 import BeautifulSoup

from shared.scraping.motor import Motor
from shared.scraping.page_strategy import PageScrapeStrategy

from . import parser as ph_parser
from .parser import BASE_DOMAIN, DEFAULT_PAGE_SIZE, PalacioConstructorPageStrategy

_DEFAULT_PAGE_SIZE = DEFAULT_PAGE_SIZE


class PalacioDeHierro(Motor):
    """Scrape Palacio de Hierro search and category listing pages."""

    PROVIDER_KEY = "ph"
    BASE_DOMAIN = BASE_DOMAIN
    PAGE_STRATEGY = PalacioConstructorPageStrategy(base_domain=BASE_DOMAIN)

    def __init__(
        self,
        job_id: str,
        url: str,
        *,
        storage_path: str,
        page_strategy: PageScrapeStrategy | None = None,
    ) -> None:
        strategy = page_strategy or PalacioConstructorPageStrategy(base_domain=self.BASE_DOMAIN)
        super().__init__(
            job_id,
            url,
            storage_path=storage_path,
            page_strategy=strategy,
        )

    def _parse_grid(self, soup: BeautifulSoup) -> List[dict]:
        return ph_parser.parse_grid(soup, base_domain=self.BASE_DOMAIN)

    def _next_url(
        self,
        current_url: str,
        items_on_page: int,
        total: int,
        page_size: int,
    ) -> Optional[str]:
        return ph_parser.next_url(
            current_url=current_url,
            items_on_page=items_on_page,
            total=total,
            page_size=page_size,
        )

    def _page_size(self, soup: BeautifulSoup) -> int:
        return ph_parser.page_size(soup)

    def _total(self, soup: BeautifulSoup) -> int:
        return ph_parser.total_results(soup)
