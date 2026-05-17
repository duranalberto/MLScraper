import logging

from bs4 import BeautifulSoup
from shared.scraping.motor import Motor

from . import parser as ml_parser
from .options import Category
from .urls import construct_search_url

logger = logging.getLogger(__name__)


class MercadoLibre(Motor):
    PROVIDER_KEY = "ml"

    def __init__(
        self,
        search_term: str,
        category: Category = Category.consolas_videojuegos,
        *,
        url: str | None = None,
        storage_path: str,
    ):
        super().__init__(
            search_term,
            url or construct_search_url(search_term, category),
            storage_path=storage_path,
        )

    def scrape_page(self, body):
        result = ml_parser.parse_search_page(
            body.get("content", ""),
            body.get("url", self.url),
        )
        if result.blocked_reason:
            self._scrape_incomplete = True
            self.mark_blocked(result.blocked_reason, self.BLOCKED_BACKOFF_SECONDS)
            if self.debug:
                logger.warning(
                    "Mercado Libre returned a blocked/gated page (%s) for '%s' at %s.",
                    result.blocked_reason,
                    self.search_term,
                    body.get("url", self.url),
                )
            return result.items, None

        if result.incomplete_reason:
            self._scrape_incomplete = True
            self.blocked_reason = result.incomplete_reason
            return result.items, None

        return result.items, result.next_url

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
