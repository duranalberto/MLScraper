from __future__ import annotations

from functools import lru_cache
import re
import urllib.parse

import requests

from .options import (
    Brand,
    Category,
    LIVERPOOL_SELLER_REFINEMENT_NAME,
    LIVERPOOL_SELLER_REFINEMENT_VALUE,
    Page,
    resolve_page,
)

BASE_URL = "https://www.liverpool.com.mx/tienda"
FILTER_URL = "https://www.liverpool.com.mx/getPlpFilter"
REQUEST_TIMEOUT_SECONDS = 15


class LiverpoolResolverError(ValueError):
    """Raised when Liverpool cannot provide a verified seller-filtered URL."""


def _query_value(query: str | None) -> str:
    return str(query or "").strip()


def _resolve_page_aliases(
    page: str | Page | None,
    category: str | Category | None,
) -> Page | None:
    if page in (None, "") and category in (None, ""):
        return None
    page_value = resolve_page(page) if page not in (None, "") else None
    category_value = resolve_page(category) if category not in (None, "") else None
    if page_value is not None and category_value is not None and page_value != category_value:
        raise ValueError(
            "Liverpool 'page' and legacy 'category' refer to different pages: "
            f"{page_value.name!r} != {category_value.name!r}."
        )
    return page_value or category_value


def _response_main_content(payload: dict) -> dict:
    """Return Liverpool's main content object from known resolver shapes."""
    main_content = payload.get("mainContent")
    if isinstance(main_content, dict):
        return main_content

    data = payload.get("data")
    if isinstance(data, dict):
        main_content = data.get("mainContent")
        if isinstance(main_content, dict):
            return main_content

    raise LiverpoolResolverError(
        "Liverpool seller-filter resolver returned no mainContent. Provide an explicit url."
    )


def _selected_refinement_values(main_content: dict, name: str) -> set[str]:
    """Collect selected refinement values for a Liverpool navigation name."""
    values: set[str] = set()
    selected_navigation = main_content.get("selectedNavigation") or ()
    if not isinstance(selected_navigation, list):
        return values

    for navigation in selected_navigation:
        if not isinstance(navigation, dict) or navigation.get("name") != name:
            continue
        refinements = navigation.get("refinements") or ()
        if not isinstance(refinements, list):
            continue
        for refinement in refinements:
            if isinstance(refinement, dict) and refinement.get("value") is not None:
                values.add(str(refinement["value"]))
    return values


def _validate_seller_navigation(main_content: dict) -> None:
    """Require Liverpool's selected seller refinement in a resolver response."""
    seller_values = _selected_refinement_values(main_content, LIVERPOOL_SELLER_REFINEMENT_NAME)
    if LIVERPOOL_SELLER_REFINEMENT_VALUE not in seller_values:
        raise LiverpoolResolverError(
            "Liverpool seller-filter resolver did not select Liverpool as seller. "
            "Provide an explicit url."
        )


def _validate_page_navigation(main_content: dict, page: Page) -> None:
    """Require Liverpool's selected page ancestor in a resolver response."""
    ancestor_values = _selected_refinement_values(main_content, "ancestors")
    category_id = page.value.category_id
    if category_id not in ancestor_values:
        raise LiverpoolResolverError(
            f"Liverpool seller-filter resolver did not select page ancestor {category_id!r}. "
            "Provide an explicit url."
        )


def _extract_encrypted_url(main_content: dict) -> str:
    """Return Liverpool's encrypted ``N-`` URL segment from a resolver response."""
    original_request = main_content.get("originalRequest")
    if not isinstance(original_request, dict):
        raise LiverpoolResolverError(
            "Liverpool seller-filter resolver returned no originalRequest. "
            "Provide an explicit url."
        )

    encrypted_url = str(original_request.get("encryptedFullUrl") or "").strip()
    if not encrypted_url:
        raise LiverpoolResolverError(
            "Liverpool seller-filter resolver returned no encrypted URL. "
            "Provide an explicit url."
        )

    if not encrypted_url.startswith("N-"):
        raise LiverpoolResolverError(
            "Liverpool seller-filter resolver returned an unexpected URL segment. "
            "Provide an explicit url."
        )

    return encrypted_url


def _resolver_params(
    *,
    query: str | None = None,
    page: Page | None = None,
) -> dict[str, str]:
    """Build the Liverpool filter endpoint params for seller-filter resolution."""
    params = {
        "Path": "PLP",
        "label": LIVERPOOL_SELLER_REFINEMENT_NAME,
        "Fs": LIVERPOOL_SELLER_REFINEMENT_VALUE,
        "displayName": "Vendido por",
        "orValue": "true",
    }

    query_value = _query_value(query)
    if query_value:
        params["s"] = query_value

    if page is not None:
        metadata = page.value
        params["categoryId"] = metadata.category_id
        params["categoryName"] = metadata.display_name

    return params


def _resolver_referer(*, query: str | None = None, page: Page | None = None) -> str:
    """Return a browser-like referer for Liverpool's filter endpoint."""
    if page is not None:
        return build_canonical_page_url(page, show_plp=True)

    query_value = _query_value(query)
    if query_value:
        return f"{BASE_URL}?s={urllib.parse.quote_plus(query_value)}"

    return BASE_URL


@lru_cache(maxsize=128)
def _resolve_seller_filtered_segment(
    query: str = "",
    page_name: str = "",
) -> str:
    """Resolve and validate a Liverpool seller-filtered encrypted URL segment."""
    page = Page[page_name] if page_name else None
    query_value = _query_value(query)

    try:
        response = requests.get(
            FILTER_URL,
            params=_resolver_params(query=query_value, page=page),
            headers={
                "Accept": "application/json",
                "Referer": _resolver_referer(query=query_value, page=page),
                "User-Agent": (
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome Safari"
                ),
            },
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as exc:
        raise LiverpoolResolverError(
            "Liverpool seller-filter resolver request failed. Provide an explicit url."
        ) from exc
    except ValueError as exc:
        raise LiverpoolResolverError(
            "Liverpool seller-filter resolver returned invalid JSON. Provide an explicit url."
        ) from exc

    if not isinstance(payload, dict):
        raise LiverpoolResolverError(
            "Liverpool seller-filter resolver returned an unexpected payload. "
            "Provide an explicit url."
        )

    main_content = _response_main_content(payload)
    _validate_seller_navigation(main_content)
    if page is not None:
        _validate_page_navigation(main_content, page)

    return _extract_encrypted_url(main_content)


def build_liverpool_url(
    search_term: str,
    *,
    query: str | None = None,
    page: str | Page | None = None,
    category: str | Category | None = None,
    brand: Brand | str | None = None,
) -> str:
    """Build a seller-filtered Liverpool URL from structured job fields.

    Args:
        search_term: Job label and global search fallback when ``query`` is
            omitted.
        query: Optional Liverpool search query.
        page: Optional known Liverpool page.
        category: Legacy alias for ``page``.
        brand: Unsupported brand/facet selector. Use explicit ``url`` instead.

    Returns:
        A Liverpool listing URL that filters to Liverpool as seller.

    Raises:
        ValueError: If a page is unknown, seller URL resolution fails, or an
            unsupported generated filter is requested.
    """
    if brand not in (None, ""):
        raise ValueError(
            "Liverpool brand filters require an explicit url; generated URLs only support "
            "seller-filtered page and query routes."
        )

    page_value = _resolve_page_aliases(page, category)
    if page_value is not None:
        return build_page_url(page_value, query=query)

    query_value = _query_value(query) or search_term
    return build_search_url(query_value)


def preview_liverpool_url(
    *,
    search_term: str = "",
    query: str | None = None,
    page: str | Page | None = None,
    category: str | Category | None = None,
    brand: Brand | str | None = None,
    url: str | None = None,
    show_plp: bool = False,
) -> str:
    """Return the final Liverpool URL for manual testing.

    Args:
        search_term: Optional global search fallback when ``query`` is omitted.
        query: Optional Liverpool search query.
        page: Optional Liverpool page name or enum member.
        category: Legacy alias for ``page``.
        brand: Unsupported generated brand/facet selector.
        url: Optional explicit URL. When set, it is returned unchanged.
        show_plp: When true with a page, return its seller-filtered PLP URL.

    Returns:
        The final URL string without creating a motor or scraping anything.

    Raises:
        ValueError: If an unknown page is provided, no input is usable, or a
            generated filter combination is unsupported.
    """
    if url:
        return url

    page_value = _resolve_page_aliases(page, category)
    if show_plp:
        if page_value is None:
            raise ValueError("Provide a Liverpool page when show_plp=True.")
        return build_page_url(page_value)

    if not (query or search_term or page_value):
        raise ValueError("Provide query, search_term, page, category, or explicit url.")

    return build_liverpool_url(
        search_term,
        query=query,
        page=page_value,
        brand=brand,
    )


def build_page_url(page: str | Page, *, query: str | None = None) -> str:
    """Build a verified Liverpool-seller URL for a documented page.

    Page-scoped queries intentionally omit the human slug. Liverpool preserves
    both seller and ancestor refinements for ``/tienda/N-{token}?s=query`` but
    currently drops them when the same query is appended to the slugged URL.
    """
    page_value = resolve_page(page)
    metadata = page_value.value
    segment = _resolve_seller_filtered_segment(page_name=page_value.name)
    query_value = _query_value(query)
    if query_value:
        return f"{BASE_URL}/{segment}?s={urllib.parse.quote_plus(query_value)}"

    encoded_slug = urllib.parse.quote(metadata.slug, safe="")
    return f"{BASE_URL}/{encoded_slug}/{segment}"


def build_canonical_page_url(page: str | Page, *, show_plp: bool = False) -> str:
    """Build the documented canonical page URL without seller filtering."""
    metadata = resolve_page(page).value
    if show_plp:
        separator = "&" if urllib.parse.urlparse(metadata.canonical_url).query else "?"
        return f"{metadata.canonical_url}{separator}showPLP"
    return metadata.canonical_url


def build_search_url(query: str) -> str:
    """Build a global Liverpool search URL filtered to Liverpool as seller."""
    query_value = _query_value(query)
    if not query_value:
        raise ValueError("Liverpool search query cannot be blank.")
    segment = _resolve_seller_filtered_segment(query=query_value)
    return f"{BASE_URL}/{segment}"


def current_page_number(url: str) -> int:
    """Return the Liverpool pagination number from a URL path."""
    parsed = urllib.parse.urlparse(url)
    match = re.search(r"/page-(\d+)/?$", parsed.path.rstrip("/"))
    return int(match.group(1)) if match else 1


def append_page_segment(url: str, page: int) -> str:
    """Append Liverpool pagination before query and fragment components."""
    parsed = urllib.parse.urlparse(url)
    path = re.sub(r"/page-\d+/?$", "", parsed.path.rstrip("/"))
    path = f"{path}/page-{page}"
    return urllib.parse.urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            path,
            parsed.params,
            parsed.query,
            parsed.fragment,
        )
    )
