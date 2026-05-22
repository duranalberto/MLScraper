"""Mercado Libre product listing URL builders."""

from __future__ import annotations

import re
import unicodedata
import urllib.parse
from enum import Enum
from typing import TypeVar

from .options import Category, Seller, State

BASE_URL = "https://listado.mercadolibre.com.mx"
_GLOBAL_SEARCH_SUFFIX = "_NoIndex_True"

Option = TypeVar("Option", bound=Enum)


def _slug(value: str, *, field_name: str) -> str:
    """Normalize a user-facing Mercado Libre route value into a slug."""
    normalized = unicodedata.normalize("NFKD", value or "")
    normalized = normalized.encode("ascii", "ignore").decode("ascii")
    normalized = normalized.casefold().strip()
    normalized = re.sub(r"[^a-z0-9]+", "-", normalized)
    slug = re.sub(r"-+", "-", normalized).strip("-")
    if not slug:
        raise ValueError(f"Mercado Libre {field_name} cannot be blank.")
    return slug


def _option(
    value: Option | str | None,
    enum_type: type[Option],
    field_name: str,
) -> Option | None:
    """Resolve an enum option from a member or config-style enum key."""
    if value in (None, ""):
        return None
    if isinstance(value, enum_type):
        return value

    raw = str(value).strip()
    try:
        return enum_type[raw]
    except KeyError as exc:
        valid = ", ".join(option.name for option in enum_type)
        raise ValueError(
            f"Unknown Mercado Libre {field_name} {raw!r}. Valid values: {valid}."
        ) from exc


def _route(*segments: str, trailing_slash: bool = False) -> str:
    path = "/".join(segment.strip("/") for segment in segments if segment)
    url = f"{BASE_URL}/{path}" if path else BASE_URL
    return f"{url}/" if trailing_slash else url


def get_identifier(url: str) -> str:
    """Return the best available Mercado Libre product identifier from a URL."""
    if not url:
        return ""

    parsed = urllib.parse.urlparse(url)
    qs = urllib.parse.parse_qs(parsed.query)

    wid = qs.get("wid", [""])[0]
    if wid:
        return wid

    match = re.search(r"/up/(MLMU\d+)", url)
    if match:
        return match.group(1)

    match = re.search(r"/p/(MLM\d+)", url)
    if match:
        return match.group(1)

    match = re.search(r"(MLM-?\d+|MLMU\d+)", url)
    if match:
        return match.group(1)

    return url


def build_global_search_url(
    query: str,
    *,
    category: Category | str | None = None,
    state: State | str | None = None,
) -> str:
    """Build a Mercado Libre global listing URL.

    Args:
        query: Global search query.
        category: Optional documented category route.
        state: Optional item condition filter.

    Returns:
        Global listing URL ending with Mercado Libre's search suffix.

    Raises:
        ValueError: If a query or enum-like option is invalid.
    """
    category_value = _option(category, Category, "category")
    state_value = _option(state, State, "state")
    segments = [*(category_value.value.path if category_value else ())]
    if state_value is not None:
        segments.append(state_value.value)
    segments.append(f"{_slug(query, field_name='global search query')}{_GLOBAL_SEARCH_SUFFIX}")
    return _route(*segments)


def build_store_url(
    seller: Seller | str,
    *,
    query: str | None = None,
    category: Category | str | None = None,
    state: State | str | None = None,
) -> str:
    """Build a known Mercado Libre seller listing URL.

    Args:
        seller: Known seller storefront.
        query: Optional store-scoped query.
        category: Optional documented category route.
        state: Optional item condition filter on a category route.

    Returns:
        Store listing URL for the requested supported route shape.

    Raises:
        ValueError: If options are invalid or a store state filter is supplied
            without a category route.
    """
    seller_value = _option(seller, Seller, "seller")
    if seller_value is None:
        raise ValueError("Mercado Libre store URL requires a seller.")

    category_value = _option(category, Category, "category")
    state_value = _option(state, State, "state")
    query_value = str(query or "").strip()

    if state_value is not None and category_value is None:
        raise ValueError(
            "Mercado Libre store state filters require a category; use explicit url for "
            "unmodeled store routes."
        )

    segments = [*seller_value.value.listing_path]
    if category_value is None:
        if query_value:
            segments.append(_slug(query_value, field_name="store query"))
            return _route(*segments)
        return _route(*segments, trailing_slash=True)

    segments.extend(("listado", *category_value.value.path))
    if state_value is not None:
        segments.append(state_value.value)
    if query_value:
        segments.append(_slug(query_value, field_name="store query"))
        return _route(*segments)
    return _route(*segments, trailing_slash=True)


def build_mercado_libre_url(
    *,
    query: str | None = None,
    seller: Seller | str | None = None,
    category: Category | str | None = None,
    state: State | str | None = None,
) -> str:
    """Build a generated Mercado Libre URL from structured job fields.

    Args:
        query: Optional global or seller-scoped query. Global searches require
            a non-blank query.
        seller: Optional known seller storefront.
        category: Optional documented category route.
        state: Optional item condition filter.

    Returns:
        Generated store or global listing URL.

    Raises:
        ValueError: If structured fields cannot form a supported URL.
    """
    seller_value = _option(seller, Seller, "seller")
    if seller_value is not None:
        return build_store_url(
            seller_value,
            query=query,
            category=category,
            state=state,
        )

    return build_global_search_url(str(query or "").strip(), category=category, state=state)


def preview_mercado_libre_url(
    *,
    query: str | None = None,
    seller: Seller | str | None = None,
    category: Category | str | None = None,
    state: State | str | None = None,
    url: str | None = None,
) -> str:
    """Return a final Mercado Libre URL without creating a motor."""
    if url:
        return url
    if not (query or seller):
        raise ValueError("Provide query, seller, or explicit url.")
    return build_mercado_libre_url(
        query=query,
        seller=seller,
        category=category,
        state=state,
    )
