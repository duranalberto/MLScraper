"""Amazon Mexico search URL builders."""

from __future__ import annotations

import urllib.parse
from enum import Enum
from typing import TypeVar

from .options import Brand, Seller

BASE_URL = "https://www.amazon.com.mx"
SEARCH_PATH = "/s"

Option = TypeVar("Option", bound=Enum)


def _option(
    value: Option | str | None,
    enum_type: type[Option],
    field_name: str,
) -> Option | None:
    """Resolve an Amazon enum option from a member or config-style key."""
    if value in (None, ""):
        return None
    if isinstance(value, enum_type):
        return value

    raw = str(value).strip()
    try:
        return enum_type[raw]
    except KeyError as exc:
        valid = ", ".join(option.name for option in enum_type)
        raise ValueError(f"Unknown Amazon {field_name} {raw!r}. Valid values: {valid}.") from exc


def _query_value(query: str | None) -> str:
    """Return Amazon's normalized generated search query when one exists."""
    value = str(query or "").strip().lower()
    return value


def _refinements(seller: Seller | None, brand: Brand | None) -> str:
    """Return Amazon ``rh`` refinements in its documented filter order."""
    filters: list[str] = []
    if seller is not None and seller is not Seller.none:
        filters.append(f"p_6:{seller.value}")
    if brand is not None:
        filters.append(f"p_123:{brand.value}")
    return ",".join(filters)


def build_search_url(
    query: str | None = None,
    *,
    seller: Seller | str | None = None,
    brand: Brand | str | None = None,
) -> str:
    """Build a generated Amazon Mexico search URL.

    Args:
        query: Optional Amazon search text.
        seller: Optional documented seller refinement.
        brand: Optional documented Marca refinement.

    Returns:
        Search URL with an optional ``k`` query and optional ``rh``
        refinements.

    Raises:
        ValueError: If no query or refinement can form a generated URL, or an
            enum-like option is invalid.
    """
    seller_value = _option(seller, Seller, "seller")
    brand_value = _option(brand, Brand, "brand")
    params = {}
    query_value = _query_value(query)
    if query_value:
        params["k"] = query_value

    refinement_value = _refinements(seller_value, brand_value)
    if refinement_value:
        params["rh"] = refinement_value
    if not params:
        raise ValueError("Provide an Amazon query, seller, or brand refinement.")

    return urllib.parse.urlunparse(
        (
            "https",
            "www.amazon.com.mx",
            SEARCH_PATH,
            "",
            urllib.parse.urlencode(params),
            "",
        )
    )


def build_amazon_url(
    *,
    query: str | None = None,
    seller: Seller | str | None = None,
    brand: Brand | str | None = None,
) -> str:
    """Build an Amazon URL from structured job fields.

    Args:
        query: Optional Amazon search query. When omitted, generated URLs may
            still use configured refinements such as a seller catalogue.
        seller: Optional documented seller refinement.
        brand: Optional documented Marca refinement.

    Returns:
        Generated Amazon search URL.

    Raises:
        ValueError: If structured fields cannot form a generated Amazon URL.
    """
    return build_search_url(query, seller=seller, brand=brand)


def preview_amazon_url(
    *,
    query: str | None = None,
    seller: Seller | str | None = None,
    brand: Brand | str | None = None,
    url: str | None = None,
) -> str:
    """Return the final Amazon URL without creating a motor.

    Args:
        query: Optional Amazon search query. Refinement-only previews can omit
            it when seller or brand inputs form a URL.
        seller: Optional documented seller refinement.
        brand: Optional documented Marca refinement.
        url: Optional explicit URL. When set, it is returned unchanged.

    Returns:
        Explicit or generated Amazon search URL.

    Raises:
        ValueError: If no usable generated URL inputs are provided or options
            are invalid.
    """
    if url:
        return url
    if not (query or seller or brand):
        raise ValueError("Provide query, seller, brand, or explicit url.")
    return build_amazon_url(query=query, seller=seller, brand=brand)
