"""Amazon Mexico search result page parser and page-scrape strategy."""

from __future__ import annotations

import re
import urllib.parse
from typing import Any

from bs4 import BeautifulSoup, Tag

from shared.scraping.page_strategy import PageScrapeResult

DEFAULT_DOMAIN = "https://www.amazon.com.mx"
ParseResult = PageScrapeResult


class AmazonSearchPageStrategy:
    """Page-scrape strategy for Amazon Mexico search result listings."""

    def __init__(self, *, domain: str = DEFAULT_DOMAIN) -> None:
        self.domain = domain

    def parse_page(
        self,
        content: str,
        url: str,
        *,
        job_id: str = "",
    ) -> PageScrapeResult:
        """Parse an Amazon search result HTML document into a :class:`PageScrapeResult`."""
        return parse_search_page(
            content,
            url,
            domain=self.domain,
            job_id=job_id,
        )


def parse_search_page(
    html: str,
    current_url: str,
    *,
    domain: str = DEFAULT_DOMAIN,
    job_id: str = "",
) -> PageScrapeResult:
    """Parse an Amazon Mexico search result page into product items and next-page URL.

    Args:
        html: Raw HTML content from an Amazon search page.
        current_url: Current page URL.
        domain: Base Amazon domain used to resolve product and pagination links.
        job_id: Optional job identifier for diagnostics.

    Returns:
        A :class:`PageScrapeResult` containing parsed items, optional ``next_url``,
        and block/incompleteness metadata when the page has no valid results.
    """
    soup = BeautifulSoup(html or "", "lxml")
    blocked_reason = _blocked_page_reason(soup)
    if blocked_reason:
        return PageScrapeResult(
            items=[],
            next_url=None,
            blocked_reason=blocked_reason,
            incomplete=True,
        )

    items_div = soup.find_all("div", {"data-component-type": "s-search-result"})
    if not items_div:
        return PageScrapeResult(
            items=[],
            next_url=None,
            incomplete_reason="amazon_results_missing",
            incomplete=True,
        )

    items: list[dict[str, Any]] = []
    for item in items_div:
        parsed = _parse_search_item(item, domain=domain)
        if parsed is not None:
            items.append(parsed)

    next_url: str | None = None
    next_tag = soup.select_one("a.s-pagination-next, span.s-pagination-next a")
    href = next_tag.get("href") if next_tag else None
    if isinstance(href, str) and href:
        next_url = urllib.parse.urljoin(domain, href)

    return PageScrapeResult(items=items, next_url=next_url)


def _parse_search_item(item: Tag, *, domain: str = DEFAULT_DOMAIN) -> dict[str, Any] | None:
    """Extract a single product dictionary from an Amazon ``s-search-result`` card."""
    asin = item.get("data-asin")
    if not asin or not isinstance(asin, str):
        return None

    try:
        title_tag = item.select_one("h2 span") or item.select_one("h2")
        if not title_tag:
            return None

        title = title_tag.get_text(strip=True)
        if not title:
            return None

        price_tag = item.select_one("span.a-price span.a-offscreen")
        if not price_tag:
            return None

        raw_price = price_tag.get_text()
        price_str = re.sub(r"[^\d.]", "", raw_price.replace(",", ""))
        price_val = float(price_str) if price_str else 0.0
    except ValueError, AttributeError:
        return None

    return {
        "identifier": asin,
        "url": f"{domain}/dp/{asin}/",
        "title": title,
        "price": price_val,
    }


def _blocked_page_reason(soup: BeautifulSoup) -> str | None:
    """Detect Amazon CAPTCHA or automated-access block pages."""
    if soup.find("form", attrs={"action": "/errors/validateCaptcha"}):
        return "amazon_captcha_blocked"
    text = soup.get_text(" ", strip=True).lower()
    if "api-services-support@amazon.com" in text or "validatecaptcha" in text:
        return "amazon_captcha_blocked"
    return None
