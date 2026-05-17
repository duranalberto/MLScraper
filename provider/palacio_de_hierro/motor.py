import json
import logging
import urllib.parse
from typing import Optional, Tuple, List

from bs4 import BeautifulSoup
from scraper.motor import Motor

logger = logging.getLogger(__name__)

_DEFAULT_PAGE_SIZE = 52


class PalacioDeHierro(Motor):
    PROVIDER_KEY = "ph"
    BASE_DOMAIN = "https://www.elpalaciodehierro.com"

    def __init__(self, search_term: str, url: str, *, storage_path: str):
        super().__init__(search_term, url, storage_path=storage_path)

    def scrape_page(self, body: dict) -> Tuple[List[dict], Optional[str]]:
        soup = BeautifulSoup(body.get("content", ""), "lxml")
        items = self._parse_grid(soup)

        if not items:
            self._scrape_incomplete = True
            logger.warning("[PH] No product tiles found for '%s'.", self.search_term)
            return [], None

        next_url = self._next_url(
            current_url=body.get("url", self.url),
            items_on_page=len(items),
            total=self._total(soup),
            page_size=self._page_size(soup),
        )
        return items, next_url

    def _parse_grid(self, soup: BeautifulSoup) -> List[dict]:
        items: List[dict] = []
        for tile in soup.select("div[data-cnstrc-item-section='Products']"):
            identifier = tile.get("data-pid") or tile.get("data-cnstrc-item-id", "")
            title = tile.get("data-cnstrc-item-name", "").strip()
            raw_price = tile.get("data-cnstrc-item-price", "0")

            if not identifier or not title:
                continue

            try:
                price = float(raw_price)
            except ValueError:
                price = 0.0

            link = tile.select_one("a[href]")
            url = link["href"] if link else ""
            if url.startswith("/"):
                url = f"{self.BASE_DOMAIN}{url}"

            items.append(
                {
                    "identifier": str(identifier),
                    "title": title,
                    "price": price,
                    "url": url,
                }
            )
        return items

    def _next_url(self, current_url, items_on_page, total, page_size) -> Optional[str]:
        if total <= 0 or items_on_page < page_size:
            return None

        parsed = urllib.parse.urlparse(current_url)
        qs = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
        current_start = int(qs.get("start", ["0"])[0] or 0)
        next_start = current_start + page_size

        if next_start >= total:
            return None

        qs["start"] = [str(next_start)]
        new_query = urllib.parse.urlencode(qs, doseq=True)
        return urllib.parse.urlunparse(
            (
                parsed.scheme,
                parsed.netloc,
                parsed.path,
                parsed.params,
                new_query,
                parsed.fragment,
            )
        )

    def _page_size(self, soup: BeautifulSoup) -> int:
        section = soup.select_one('section[data-component="search/ConstructorSearch"]')
        if section and section.has_attr("data-component-options"):
            try:
                return int(
                    json.loads(section["data-component-options"]).get(
                        "pageSize", _DEFAULT_PAGE_SIZE
                    )
                )
            except json.JSONDecodeError, ValueError:
                pass
        return _DEFAULT_PAGE_SIZE

    def _total(self, soup: BeautifulSoup) -> int:
        grid = soup.select_one("[data-cnstrc-num-results]")
        if grid:
            try:
                return int(grid["data-cnstrc-num-results"])
            except ValueError, KeyError:
                pass
        return 0
