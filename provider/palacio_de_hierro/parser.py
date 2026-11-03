"""Palacio de Hierro listing page parser and page-scrape strategy."""

from __future__ import annotations

import json
import logging
import urllib.parse
from typing import Any

from bs4 import BeautifulSoup

from shared.scraping.page_strategy import PageScrapeResult

logger = logging.getLogger(__name__)

BASE_DOMAIN = "https://www.elpalaciodehierro.com"
DEFAULT_PAGE_SIZE = 52
ParseResult = PageScrapeResult


class PalacioConstructorPageStrategy:
    """Page-scrape strategy for Palacio de Hierro Constructor.io listing grids."""

    def __init__(self, *, base_domain: str = BASE_DOMAIN) -> None:
        self.base_domain = base_domain

    def parse_page(
        self,
        content: str,
        url: str,
        *,
        job_id: str = "",
    ) -> PageScrapeResult:
        """Parse a Palacio de Hierro HTML page into a :class:`PageScrapeResult`."""
        return parse_listing_page(
            content,
            url,
            base_domain=self.base_domain,
            job_id=job_id,
        )


def parse_listing_page(
    html: str,
    current_url: str,
    *,
    base_domain: str = BASE_DOMAIN,
    job_id: str = "",
) -> PageScrapeResult:
    """Parse a Palacio de Hierro listing page into product records and pagination."""
    soup = BeautifulSoup(html or "", "lxml")
    items = parse_grid(soup, base_domain=base_domain)

    if not items:
        logger.warning("[PH] No product tiles found for '%s'.", job_id)
        return PageScrapeResult(
            items=[],
            next_url=None,
            incomplete_reason="palacio_empty_grid",
            incomplete=True,
        )

    next_page = next_url(
        current_url=current_url,
        items_on_page=len(items),
        total=total_results(soup),
        page_size=page_size(soup),
    )
    return PageScrapeResult(items=items, next_url=next_page)


def parse_grid(
    soup: BeautifulSoup,
    *,
    base_domain: str = BASE_DOMAIN,
) -> list[dict[str, Any]]:
    """Extract product items from Palacio de Hierro's Constructor product tiles."""
    items: list[dict[str, Any]] = []
    for tile in soup.select("div[data-cnstrc-item-section='Products']"):
        identifier = tile.get("data-pid") or tile.get("data-cnstrc-item-id", "")
        raw_title = tile.get("data-cnstrc-item-name", "")
        title = raw_title.strip() if isinstance(raw_title, str) else ""
        raw_price = tile.get("data-cnstrc-item-price", "0")

        if not identifier or not title:
            continue

        try:
            price = float(raw_price) if isinstance(raw_price, str) else 0.0
        except ValueError:
            price = 0.0

        link = tile.select_one("a[href]")
        href = link.get("href") if link else None
        url = href if isinstance(href, str) else ""
        if url.startswith("/"):
            url = f"{base_domain}{url}"

        items.append(
            {
                "identifier": str(identifier),
                "title": title,
                "price": price,
                "url": url,
            }
        )
    return items


def next_url(
    current_url: str,
    items_on_page: int,
    total: int,
    page_size: int,
) -> str | None:
    """Calculate the next ``start`` query-parameter URL when more items remain."""
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


def page_size(soup: BeautifulSoup) -> int:
    """Extract the configured page size from ``ConstructorSearch`` options."""
    section = soup.select_one('section[data-component="search/ConstructorSearch"]')
    if section and section.has_attr("data-component-options"):
        options = section.get("data-component-options")
        if not isinstance(options, str):
            return DEFAULT_PAGE_SIZE
        try:
            return int(json.loads(options).get("pageSize", DEFAULT_PAGE_SIZE))
        except json.JSONDecodeError, ValueError:
            pass
    return DEFAULT_PAGE_SIZE


def total_results(soup: BeautifulSoup) -> int:
    """Extract the total result count from ``[data-cnstrc-num-results]``."""
    grid = soup.select_one("[data-cnstrc-num-results]")
    if grid:
        raw_total = grid.get("data-cnstrc-num-results")
        if not isinstance(raw_total, str):
            return 0
        try:
            return int(raw_total)
        except ValueError:
            pass
    return 0
