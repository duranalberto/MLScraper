"""
provider/palacio_de_hierro/motor.py

Architecture change — SSR HTML parsing replaces Constructor.io API calls
─────────────────────────────────────────────────────────────────────────
The previous implementation scraped the HTML only to extract a Constructor.io
API key and page-size config, then made a second outbound HTTP request to
ac.cnstrc.com to fetch the actual product data.

The uploaded HTML (buscar?q=macbook-air) shows this is no longer necessary:
  • `ssrEnabled: true` in data-component-options confirms the server already
    renders the full product grid into the initial HTML response.
  • All 43 results (= data-cnstrc-num-results) are present as
    div[data-cnstrc-item-section='Products'] nodes, each carrying:
      – data-pid / data-cnstrc-item-id  → identifier
      – data-cnstrc-item-name           → title
      – data-cnstrc-item-price          → price
      – first <a href>                  → canonical product URL (absolute)
  • pageSize is 52 (was 28); total_num_results is embedded in
    data-cnstrc-num-results on the grid container, enabling exact
    ceil-division pagination without a round-trip to the API.
  • Pagination advances via the `start` query param on the same page URL
    (standard SFCC / Constructor pattern), not through a `params` JSON blob.

Removed
───────
  • All requests / aiohttp imports for the Constructor.io API call
  • _fetch_constructor_results, _extract_items (API path)
  • uuid / time imports (were only needed for API client-id / _dt)
  • ENV-var API-key fallback (no longer relevant)
  • The blocking requests.Session that was previously breaking the event loop

What remains
────────────
  scrape_page   – pure HTML parse, synchronous, returns (items, next_url)
  _parse_grid   – extracts items from SSR tiles
  _next_url     – builds the next-page URL from start offset
  _page_size    – reads pageSize from the component options blob (default 52)
  _total        – reads data-cnstrc-num-results from the grid container
"""

import json
import logging
import urllib.parse
from typing import Optional, Tuple, List

from bs4 import BeautifulSoup

from scraper.motor import Motor

logger = logging.getLogger(__name__)

_DEFAULT_PAGE_SIZE = 52


class PalacioDeHierro(Motor):
    BASE_DOMAIN = "https://www.elpalaciodehierro.com"

    def __init__(self, search_term: str, url: str):
        super().__init__(search_term, url)

    # ------------------------------------------------------------------
    # ENTRY POINT
    # ------------------------------------------------------------------
    def scrape_page(self, body: dict) -> Tuple[List[dict], Optional[str]]:
        """
        Parse the SSR HTML and return (items, next_url).
        No external HTTP call is made — all product data lives in the page.
        """
        soup = BeautifulSoup(body.get("content", ""), "lxml")

        items = self._parse_grid(soup)

        if not items:
            logger.warning("[PH] No product tiles found for '%s'.", self.search_term)
            return [], None

        next_url = self._next_url(
            current_url=body.get("url", self.url),
            items_on_page=len(items),
            total=self._total(soup),
            page_size=self._page_size(soup),
        )

        return items, next_url

    # ------------------------------------------------------------------
    # PRODUCT TILE EXTRACTION
    # ------------------------------------------------------------------
    def _parse_grid(self, soup: BeautifulSoup) -> List[dict]:
        """
        Every rendered product tile carries its full data as HTML attributes:
            data-pid / data-cnstrc-item-id  → identifier
            data-cnstrc-item-name           → title
            data-cnstrc-item-price          → price
            first <a href>                  → absolute product URL
        """
        items: List[dict] = []

        tiles = soup.select("div[data-cnstrc-item-section='Products']")
        for tile in tiles:
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
                    "search_term": self.search_term,
                }
            )

        return items

    # ------------------------------------------------------------------
    # PAGINATION
    # ------------------------------------------------------------------
    def _next_url(
        self,
        current_url: str,
        items_on_page: int,
        total: int,
        page_size: int,
    ) -> Optional[str]:
        """
        Builds the next-page URL by incrementing the `start` offset.
        Returns None when the current page already covers all results.

        Constructor / SFCC pagination:
            page 1 → (no start param, or start=0)
            page 2 → start=<page_size>
            page 3 → start=<page_size * 2>
            …
        """
        if total <= 0 or items_on_page < page_size:
            # Fewer items than a full page → we are on the last page
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

    # ------------------------------------------------------------------
    # HTML CONFIG HELPERS
    # ------------------------------------------------------------------
    def _page_size(self, soup: BeautifulSoup) -> int:
        """Reads pageSize from the ConstructorSearch component options blob."""
        section = soup.select_one('section[data-component="search/ConstructorSearch"]')
        if section and section.has_attr("data-component-options"):
            try:
                opts = json.loads(section["data-component-options"])
                return int(opts.get("pageSize", _DEFAULT_PAGE_SIZE))
            except (json.JSONDecodeError, ValueError) as exc:
                logger.warning("[PH] Could not parse pageSize from component options: %s", exc)
        return _DEFAULT_PAGE_SIZE

    def _total(self, soup: BeautifulSoup) -> int:
        """Reads the server-reported total result count from the grid container."""
        grid = soup.select_one("[data-cnstrc-num-results]")
        if grid:
            try:
                return int(grid["data-cnstrc-num-results"])
            except (ValueError, KeyError):
                pass
        return 0