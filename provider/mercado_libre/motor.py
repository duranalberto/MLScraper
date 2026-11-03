"""Mercado Libre provider motor implementation."""

from __future__ import annotations

from bs4 import BeautifulSoup

from shared.scraping.motor import Motor
from shared.scraping.page_strategy import PageScrapeStrategy

from . import parser as ml_parser
from .parser import MercadoLibreSearchPageStrategy


class MercadoLibre(Motor):
    """Mercado Libre scraping motor supporting DOM and Nordic JSON state strategies."""

    PROVIDER_KEY = "ml"
    PAGE_STRATEGY = MercadoLibreSearchPageStrategy()

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

    def _parse_dom_results(self, soup: BeautifulSoup, current_url: str):
        return ml_parser.parse_dom_results(soup, current_url)

    def _parse_nordic_state(self, soup: BeautifulSoup):
        return ml_parser.parse_nordic_state(soup)

    @staticmethod
    def _nordic_initial_state(soup: BeautifulSoup) -> dict | None:
        return ml_parser.nordic_initial_state(soup)

    @staticmethod
    def _nordic_component_value(polycard: dict, component_type: str, *path: str):
        return ml_parser.nordic_component_value(polycard, component_type, *path)

    @staticmethod
    def _nordic_url(metadata: dict) -> str:
        return ml_parser.nordic_url(metadata)

    def _get_page_size(self, soup: BeautifulSoup, raw_item_count: int) -> int:
        return ml_parser.get_page_size(soup, raw_item_count)

    def _next_url(self, current_url: str, items_on_page: int, page_size: int, soup: BeautifulSoup):
        return ml_parser.pagination_next_url(current_url, items_on_page, page_size, soup)

    def _has_next_page(self, soup: BeautifulSoup) -> bool:
        return ml_parser.has_next_page(soup)

    def _next_offset(self, current_url: str, page_size: int) -> int:
        return ml_parser.next_offset_value(current_url, page_size)

    @staticmethod
    def _current_offset(current_url: str) -> int:
        return ml_parser.current_offset_value(current_url)

    def _total_results(self, soup: BeautifulSoup) -> int | None:
        return ml_parser.total_results_count(soup)

    def _inject_offset(self, current_url: str, next_offset: int) -> str:
        return ml_parser.inject_offset(current_url, next_offset)

    @staticmethod
    def _blocked_page_reason(soup: BeautifulSoup) -> str | None:
        return ml_parser.blocked_page_reason(soup)
