"""Liverpool search and category listing page parser.

Supports both Liverpool's Next.js App Router React Server Component (RSC)
payloads (``self.__next_f.push`` chunks containing ``initialResults``) and the
legacy ``__NEXT_DATA__`` payload format used in older test fixtures.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from bs4 import BeautifulSoup

from .urls import append_page_segment, current_page_number

logger = logging.getLogger(__name__)

_NEXT_F_STRING_RE = re.compile(
    r"self\.__next_f\.push\(\[\s*1\s*,\s*(\"(?:\\.|[^\"\\])*\")\s*\]\)",
    re.DOTALL,
)
_RSC_UNDEFINED_RE = re.compile(r":\s*\"\$undefined\"")


@dataclass(frozen=True)
class ParseResult:
    """Parsed Liverpool listing items and pagination state.

    Args:
        items: Extracted product dictionaries with ``identifier``, ``title``,
            ``price``, and ``url``.
        next_url: URL of the next page when more pages remain, or ``None``.
        incomplete: ``True`` when no recognizable listing payload could be
            parsed from the HTML document.
    """

    items: list[dict[str, Any]]
    next_url: str | None
    incomplete: bool = False


def parse_listing_page(html: str, current_url: str, *, job_id: str = "") -> ParseResult:
    """Parse a Liverpool HTML page into product records and next-page URL.

    Args:
        html: Raw HTML string from a Liverpool search or category listing page.
        current_url: The URL that produced ``html``, used for pagination calculation.
        job_id: Optional job identifier used in diagnostic log messages.

    Returns:
        A ``ParseResult`` containing extracted product records, optional next
        page URL, and an ``incomplete`` flag when the page lacks a valid payload.
    """
    soup = BeautifulSoup(html or "", "html.parser")
    listing_data = _extract_rsc_initial_results(soup)
    if listing_data is None:
        listing_data = _extract_legacy_next_data(soup, job_id=job_id)

    if listing_data is None:
        logger.error(
            "[Liverpool] Listing payload missing or invalid for '%s'. "
            "Liverpool may have changed their page structure.",
            job_id,
        )
        return ParseResult(items=[], next_url=None, incomplete=True)

    records = listing_data.get("records")
    if not isinstance(records, list):
        logger.error(
            "[Liverpool] Unexpected JSON structure for '%s' — 'records' list not found.",
            job_id,
        )
        return ParseResult(items=[], next_url=None, incomplete=True)

    items: list[dict[str, Any]] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        try:
            items.append(_parse_record(record))
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning(
                "[Liverpool] Skipping malformed record for '%s': %s",
                job_id,
                exc,
            )

    next_url = _extract_next_url(listing_data, current_url)
    return ParseResult(items=items, next_url=next_url, incomplete=False)


def _extract_rsc_initial_results(soup: BeautifulSoup) -> dict[str, Any] | None:
    """Extract ``initialResults`` from Next.js App Router ``__next_f`` scripts."""
    marker = '"initialResults":'
    decoder = json.JSONDecoder()

    for script in soup.find_all("script"):
        text = script.string if script.string is not None else script.get_text()
        if not text or "initialResults" not in text:
            continue

        for match in _NEXT_F_STRING_RE.finditer(text):
            try:
                unescaped = json.loads(match.group(1))
            except json.JSONDecodeError:
                continue

            if not isinstance(unescaped, str):
                continue

            idx = unescaped.find(marker)
            if idx == -1:
                continue

            candidate = _RSC_UNDEFINED_RE.sub(": null", unescaped[idx + len(marker) :]).lstrip()
            try:
                parsed, _ = decoder.raw_decode(candidate)
            except json.JSONDecodeError:
                continue

            if isinstance(parsed, dict) and "records" in parsed:
                return parsed

    return None


def _extract_legacy_next_data(soup: BeautifulSoup, *, job_id: str = "") -> dict[str, Any] | None:
    """Extract ``mainContent`` from a legacy ``__NEXT_DATA__`` script tag."""
    root = soup.find("script", id="__NEXT_DATA__")
    if not root or not root.string:
        return None

    try:
        page_object = json.loads(root.string)
        main_content = page_object["query"]["data"]["mainContent"]
    except json.JSONDecodeError as exc:
        logger.error(
            "[Liverpool] Failed to parse __NEXT_DATA__ JSON for '%s': %s",
            job_id,
            exc,
        )
        return None
    except (KeyError, TypeError) as exc:
        logger.error(
            "[Liverpool] Unexpected JSON structure for '%s' — key %s not found.",
            job_id,
            exc,
        )
        return None

    return main_content if isinstance(main_content, dict) else None


def _parse_record(record: dict[str, Any]) -> dict[str, Any]:
    """Convert a raw Liverpool record (RSC or legacy ``allMeta``) into an item dict."""
    if isinstance(record.get("allMeta"), dict):
        meta = record["allMeta"]
        identifier = str(meta["id"]).strip()
        title = str(meta["title"]).strip()
        price = float(meta["minimumPromoPrice"])
    else:
        raw_id = record.get("productId") or record.get("id") or record.get("skuRepositoryId")
        raw_title = record.get("title") or record.get("name")
        if not raw_id:
            raise KeyError("productId")
        if not raw_title:
            raise KeyError("title")
        identifier = str(raw_id).strip()
        title = str(raw_title).strip()
        price = _extract_price(record)

    if not identifier or not title:
        raise ValueError("Empty identifier or title")

    formatted_title = title.lower().replace(" ", "-")
    return {
        "identifier": identifier,
        "title": title,
        "price": price,
        "url": f"https://www.liverpool.com.mx/tienda/pdp/{formatted_title}/{identifier}",
    }


def _extract_price(record: dict[str, Any]) -> float:
    """Extract the effective promo or sale price from an RSC product record."""
    price_info = record.get("priceInfo")
    if isinstance(price_info, dict):
        promo_price = price_info.get("promoPrice")
        if isinstance(promo_price, dict):
            for key in ("minPrice", "price", "maxPrice"):
                candidate = _positive_float(promo_price.get(key))
                if candidate is not None:
                    return candidate
        else:
            candidate = _positive_float(promo_price)
            if candidate is not None:
                return candidate

        sale_price = _positive_float(price_info.get("salePrice"))
        if sale_price is not None:
            return sale_price

        list_price = price_info.get("listPrice")
        if isinstance(list_price, dict):
            for key in ("minPrice", "price", "maxPrice"):
                candidate = _positive_float(list_price.get(key))
                if candidate is not None:
                    return candidate
        else:
            candidate = _positive_float(list_price)
            if candidate is not None:
                return candidate

    fallback = _positive_float(record.get("minimumPromoPrice"))
    if fallback is not None:
        return fallback

    raise KeyError("priceInfo")


def _positive_float(value: Any) -> float | None:
    """Convert ``value`` to a positive float when possible."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except TypeError, ValueError:
        return None
    return number if number > 0 else None


def _extract_next_url(listing_data: dict[str, Any], current_url: str) -> str | None:
    """Compute the next page URL from Liverpool ``pageInfo`` metadata."""
    try:
        page_info = listing_data["pageInfo"]
        no_of_pages = int(page_info["noOfPages"])
        current_page = current_page_number(current_url)
        next_page = current_page + 1
        if current_page < no_of_pages:
            return append_page_segment(current_url, next_page)
    except KeyError, TypeError, ValueError:
        pass
    return None
