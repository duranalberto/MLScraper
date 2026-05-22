"""Palacio de Hierro listing URL builders."""

from __future__ import annotations

import re
import unicodedata
import urllib.parse
from collections.abc import Iterable

from .options import Page, resolve_page

BASE_URL = "https://www.elpalaciodehierro.com"
SEARCH_PATH = "/buscar"

BrandInput = str | Iterable[str] | None


def _slug(value: str, *, field_name: str) -> str:
    """Normalize user-facing Palacio route inputs into URL-safe slug text."""
    normalized = unicodedata.normalize("NFKD", value or "")
    normalized = normalized.encode("ascii", "ignore").decode("ascii")
    normalized = normalized.casefold().strip()
    normalized = re.sub(r"[^a-z0-9]+", "-", normalized)
    slug = re.sub(r"-+", "-", normalized).strip("-")
    if not slug:
        raise ValueError(f"Palacio {field_name} cannot be blank.")
    return slug


def _brand_values(brands: BrandInput) -> tuple[str, ...]:
    if brands in (None, ""):
        return ()
    if isinstance(brands, str):
        return (brands,)

    try:
        values = tuple(brands)
    except TypeError as exc:
        raise ValueError("Palacio brands must be a string or iterable of strings.") from exc

    if any(not isinstance(value, str) for value in values):
        raise ValueError("Palacio brands must contain only strings.")
    return values


def brand_filter_segment(brands: BrandInput) -> str:
    """Build Palacio's alphabetized brand filter path segment.

    Args:
        brands: One brand label or an iterable of brand labels.

    Returns:
        URL-encoded path segment for brand filters, or an empty string when no
        brands are configured.

    Raises:
        ValueError: If brand values are blank, not strings, or include path
            separators.
    """
    tokens: set[str] = set()
    for brand in _brand_values(brands):
        if "/" in brand or "\\" in brand:
            raise ValueError("Palacio brand filters cannot include path separators.")
        tokens.add(_slug(brand, field_name="brand"))

    if not tokens:
        return ""

    return urllib.parse.quote("|".join(sorted(tokens)), safe="-")


def build_search_url(query: str) -> str:
    """Build a Palacio global search URL.

    Args:
        query: Storefront search query. Palacio search URLs use hyphenated query
            text for terms separated by spaces or punctuation.

    Returns:
        Palacio global search URL.

    Raises:
        ValueError: If the query cannot produce a non-blank slug.
    """
    slug = _slug(str(query or ""), field_name="search query")
    return urllib.parse.urlunparse(
        (
            "https",
            "www.elpalaciodehierro.com",
            SEARCH_PATH,
            "",
            urllib.parse.urlencode({"q": slug}),
            "",
        )
    )


def build_page_url(page: str | Page, *, brands: BrandInput = None) -> str:
    """Build a Palacio page URL with optional brand path filters.

    Args:
        page: Known Palacio page enum member or lookup label.
        brands: Optional brand labels. Multiple labels are deduplicated,
            alphabetized, joined with ``|``, and encoded as the final path
            segment.

    Returns:
        Palacio page URL ending with a trailing slash.

    Raises:
        ValueError: If the page or brand values are invalid.
    """
    page_value = resolve_page(page)
    segments = [*page_value.value.path]
    brand_segment = brand_filter_segment(brands)
    if brand_segment:
        segments.append(brand_segment)
    return f"{BASE_URL}/{'/'.join(segments)}/"


def build_palacio_url(
    *,
    query: str | None = None,
    page: str | Page | None = None,
    brands: BrandInput = None,
) -> str:
    """Build a Palacio URL from structured job fields.

    Args:
        query: Optional global Palacio search query. Global search routes
            require a non-blank query.
        page: Optional known Palacio listing page.
        brands: Optional brand filters for a page listing.

    Returns:
        Generated Palacio page or global search URL.

    Raises:
        ValueError: If page filters are mixed with a global query or the
            structured values cannot form a supported Palacio URL.
    """
    query_value = str(query or "")
    has_query = bool(query_value.strip())
    if page not in (None, ""):
        if has_query:
            raise ValueError("Palacio page URLs do not support global query fields.")
        return build_page_url(page, brands=brands)

    if _brand_values(brands):
        raise ValueError("Palacio brand filters require a page.")

    return build_search_url(query_value)


def preview_palacio_url(
    *,
    query: str | None = None,
    page: str | Page | None = None,
    brands: BrandInput = None,
    url: str | None = None,
) -> str:
    """Return the final Palacio URL for manual testing.

    Args:
        query: Optional global Palacio search query.
        page: Optional known Palacio listing page.
        brands: Optional page-scoped brand filters.
        url: Optional explicit URL. When set, it is returned unchanged.

    Returns:
        Final URL without creating a Palacio motor.

    Raises:
        ValueError: If no usable generated URL inputs are provided or a
            structured combination is unsupported.
    """
    if url:
        return url
    if not (query or page):
        raise ValueError("Provide query, page, or explicit url.")
    return build_palacio_url(query=query, page=page, brands=brands)
