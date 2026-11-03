from __future__ import annotations

from functools import lru_cache
import re
import urllib.parse

import requests

from .options import (
    Brand,
    Category,
    LIVERPOOL_SELLER_FILTER_ID,
    LIVERPOOL_SELLER_REFINEMENT_NAME,
    LIVERPOOL_SELLER_REFINEMENT_VALUE,
    Page,
    PageKind,
    resolve_page,
)

BASE_URL = "https://www.liverpool.com.mx/tienda"
FILTER_URL = "https://www.liverpool.com.mx/api/plp/search"
REQUEST_TIMEOUT_SECONDS = 15
_SESSION: requests.Session | None = None
_ORIGINAL_REQUESTS_POST = requests.post


def _get_session() -> requests.Session:
    """Return a shared HTTP session for Liverpool resolver requests."""
    global _SESSION
    if _SESSION is None:
        _SESSION = requests.Session()
    return _SESSION


TALLA_REFINEMENT_NAME = "attributes.rzlv_tallaRopa"
TALLA_ENRICH_REFINEMENT_NAME = "attributes.enrichAI_Talla"
TALLA_FILTER_IDS = {
    "26.5 cm": "YXR0cmlidXRlcy5lbnJpY2hBSV9UYWxsYTpWOjI2LjUgY20=",
    "27 cm": "YXR0cmlidXRlcy5lbnJpY2hBSV9UYWxsYTpWOjI3IGNt",
}

_SUPPORTED_ZAPATOS_TALLAS = {
    "26.5 cm": "26.5 cm",
    "26.5": "26.5 cm",
    "27 cm": "27 cm",
    "27": "27 cm",
}

# Liverpool-generated fixtures captured from production routes for Zapatos.
_ZAPATOS_TALLA_URLS = {
    ("26.5 cm",): (
        "https://www.liverpool.com.mx/tienda/zapatos/"
        "N-DSNCDwNe0TQmqDl9oaVW3NMMVWOMWKnBTxTMkuCm8FJSYNNgpfpKZJhbO%2FeHb1VtGHTmN%2F9HShTHsphfUIoyiA%3D%3D"
    ),
    ("27 cm",): (
        "https://www.liverpool.com.mx/tienda/zapatos/"
        "N-DSNCDwNe0TQmqDl9oaVW3P49z6zKiRdLU4IIpgT97FoXJTIUSUZJlJZf8BVMSBuD0Bn3ELEZFYONaFEjhb%2FKag%3D%3D"
    ),
    ("26.5 cm", "27 cm"): (
        "https://www.liverpool.com.mx/tienda/zapatos/"
        "N-DSNCDwNe0TQmqDl9oaVW3NMMVWOMWKnBTxTMkuCm8FK8nbspJJHyymB2JB2cQAhiuNp2DrMWVxMOlgTqk%2BZcRA%3D%3D"
    ),
}

_ZAPATOS_SELLER_TALLA_URLS = {
    ("26.5 cm",): (
        "https://www.liverpool.com.mx/tienda/zapatos/"
        "N-S1sLjNksKoG%2BC2c1SDPsHO5452djswD00Q%2BK5TJ2fOqRWmHi9IHo7DohJbsKzc6imfhD61Tn4E65LWhl6f0t7AaY0oFPrT%2BCxbnEWoFgLLk%3D"
    ),
    ("27 cm",): (
        "https://www.liverpool.com.mx/tienda/zapatos/"
        "N-S1sLjNksKoG%2BC2c1SDPsHO5452djswD00Q%2BK5TJ2fOozVqOODGOtunTN8e%2BvWv35ro9Gu4Wj4ohV%2F0lAwq%2BnstUtcATsuqxRHlNDb77mhq0%3D"
    ),
    ("26.5 cm", "27 cm"): (
        "https://www.liverpool.com.mx/tienda/zapatos/"
        "N-S1sLjNksKoG%2BC2c1SDPsHO5452djswD00Q%2BK5TJ2fOqRWmHi9IHo7DohJbsKzc6ie3dJdH0yzQY5Wf7pWwAqdcmJw7uqeFRVZhuwaUGwFJM%3D"
    ),
}


class LiverpoolResolverError(ValueError):
    """Raised when Liverpool cannot provide a verified seller-filtered URL."""


def _query_value(query: str | None) -> str:
    return str(query or "").strip()


def _normalize_talla_values(
    talla: str | list[str] | tuple[str, ...] | None,
) -> tuple[str, ...]:
    """Normalize, validate, and canonicalize Liverpool Zapatos talla values."""
    if talla in (None, ""):
        return ()

    raw_values: list[str]
    if isinstance(talla, str):
        raw_values = [talla]
    elif isinstance(talla, (list, tuple)):
        raw_values = [str(value) for value in talla]
    else:
        raise ValueError("Liverpool talla must be a string or a list/tuple of strings.")

    values: list[str] = []
    for raw in raw_values:
        cleaned = str(raw or "").strip()
        if not cleaned:
            continue
        canonical = _SUPPORTED_ZAPATOS_TALLAS.get(cleaned.casefold())
        if canonical is None:
            supported = ", ".join(sorted(set(_SUPPORTED_ZAPATOS_TALLAS.values())))
            raise ValueError(
                f"Unsupported Liverpool talla {cleaned!r}. Supported values: {supported}."
            )
        values.append(canonical)

    if not values:
        raise ValueError("Liverpool talla cannot be blank.")

    ordered: list[str] = []
    for value in values:
        if value not in ordered:
            ordered.append(value)
    return tuple(sorted(ordered))


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
        if any(
            key in data
            for key in ("encryptedFilters", "filtersGroups", "filter", "originalRequest")
        ):
            return data

    raise LiverpoolResolverError(
        "Liverpool seller-filter resolver returned no mainContent. Provide an explicit url."
    )


def _selected_refinement_values(main_content: dict, name: str) -> set[str]:
    """Collect selected refinement values for a Liverpool navigation name."""
    values: set[str] = set()
    selected_navigation = main_content.get("selectedNavigation") or ()
    if isinstance(selected_navigation, list):
        for navigation in selected_navigation:
            if not isinstance(navigation, dict) or navigation.get("name") != name:
                continue
            refinements = navigation.get("refinements") or ()
            if not isinstance(refinements, list):
                continue
            for refinement in refinements:
                if isinstance(refinement, dict) and refinement.get("value") is not None:
                    values.add(str(refinement["value"]))

    filters_groups = main_content.get("filtersGroups") or ()
    if isinstance(filters_groups, list):
        for group in filters_groups:
            if not isinstance(group, dict):
                continue
            dimension = str(group.get("dimensionName") or "")
            if dimension == name:
                filters = group.get("filter") or ()
                if isinstance(filters, list):
                    for item in filters:
                        if isinstance(item, dict) and item.get("selected"):
                            label = item.get("label") or item.get("value")
                            if label is not None:
                                values.add(str(label))
            elif name == "ancestors" and dimension == "Category":
                ancestors = group.get("ancestors") or ()
                if isinstance(ancestors, list):
                    for ancestor in ancestors:
                        if isinstance(ancestor, dict) and ancestor.get("selected"):
                            cat_id = ancestor.get("categoryId")
                            if cat_id is not None:
                                values.add(str(cat_id))
                                values.add(str(cat_id).upper())

    raw_filter = main_content.get("filter")
    if isinstance(raw_filter, str) and raw_filter:
        if name == LIVERPOOL_SELLER_REFINEMENT_NAME:
            for match in re.findall(r'attributes\.sellernames:\s*ANY\("([^"]+)"\)', raw_filter):
                values.add(match)
        elif name == "ancestors":
            for match in re.findall(r'attributes\.ancestors:\s*ANY\("([^"]+)"\)', raw_filter):
                values.add(match)
                values.add(match.upper())

    return values


def _validate_seller_navigation(main_content: dict) -> None:
    """Require Liverpool's selected seller refinement in a resolver response."""
    seller_values = _selected_refinement_values(main_content, LIVERPOOL_SELLER_REFINEMENT_NAME)
    if LIVERPOOL_SELLER_REFINEMENT_VALUE not in {v.casefold() for v in seller_values}:
        raise LiverpoolResolverError(
            "Liverpool seller-filter resolver did not select Liverpool as seller. "
            "Provide an explicit url."
        )


def _validate_page_navigation(main_content: dict, page: Page) -> None:
    """Require Liverpool's selected page ancestor in a resolver response."""
    ancestor_values = {v.upper() for v in _selected_refinement_values(main_content, "ancestors")}
    category_id = page.value.category_id.upper()
    if category_id not in ancestor_values:
        raise LiverpoolResolverError(
            f"Liverpool seller-filter resolver did not select page ancestor {page.value.category_id!r}. "
            "Provide an explicit url."
        )


def _extract_encrypted_url(main_content: dict) -> str:
    """Return Liverpool's encrypted ``N-`` URL segment from a resolver response."""
    encrypted_filters = main_content.get("encryptedFilters")
    if encrypted_filters is not None:
        encrypted_url = str(encrypted_filters).strip()
    else:
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
    """Build legacy Liverpool filter endpoint params for seller-filter resolution."""
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


def _resolver_payload(
    *,
    query: str | None = None,
    page: Page | None = None,
) -> dict[str, str | list[str]]:
    """Build the JSON payload for Liverpool's ``/api/plp/search`` endpoint."""
    payload: dict[str, str | list[str]] = {
        "channel": "WEB",
        "brand": "LP",
        "dataCenter": "SiteA",
        "gbi_visitorId": "",
        "appliedFilters": [LIVERPOOL_SELLER_FILTER_ID],
    }

    query_value = _query_value(query)
    if query_value:
        payload["query"] = query_value

    if page is not None:
        metadata = page.value
        payload["categoryId"] = metadata.category_id.lower()
        payload["pageCategories"] = ">".join(metadata.breadcrumb)

    return payload


def _resolver_headers(
    *,
    query: str | None = None,
    page: Page | None = None,
) -> dict[str, str]:
    """Build browser-like headers for Liverpool's ``/api/plp/search`` endpoint."""
    action = "browse-show" if page is not None else "search-show"
    return {
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "Origin": "https://www.liverpool.com.mx",
        "Referer": _resolver_referer(query=query, page=page),
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"
        ),
        "x-brand-id": "LP",
        "X-Client-Page": "plp",
        "X-Client-Component": "list",
        "X-Client-Channel": "web",
        "X-Client-Action": action,
    }


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
        post_fn = _get_session().post if requests.post is _ORIGINAL_REQUESTS_POST else requests.post
        response = post_fn(
            FILTER_URL,
            json=_resolver_payload(query=query_value, page=page),
            headers=_resolver_headers(query=query_value, page=page),
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
    *,
    query: str | None = None,
    page: str | Page | None = None,
    category: str | Category | None = None,
    brand: Brand | str | None = None,
    talla: str | list[str] | tuple[str, ...] | None = None,
) -> str:
    """Build a seller-filtered Liverpool URL from structured job fields.

    Args:
        query: Optional Liverpool search query. Search routes require a query;
            page routes may omit it.
        page: Optional known Liverpool page.
        category: Legacy alias for ``page``.
        brand: Unsupported brand/facet selector. Use explicit ``url`` instead.
        talla: Optional Zapatos-only Talla values. Supports one or more values.

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
    talla_values = _normalize_talla_values(talla)
    if talla_values:
        if page_value is None:
            raise ValueError("Liverpool talla filters require a page/category route.")
        if page_value is not Page.zapatos_hombre:
            raise ValueError(
                "Liverpool talla filters are currently supported only for 'zapatos_hombre'."
            )
        if query and _query_value(query):
            raise ValueError(
                "Liverpool generated talla filters do not support query combinations yet."
            )
        try:
            return _ZAPATOS_SELLER_TALLA_URLS[talla_values]
        except KeyError as exc:
            supported = ", ".join(" + ".join(combo) for combo in sorted(_ZAPATOS_SELLER_TALLA_URLS))
            raise ValueError(
                "Unsupported Liverpool seller+talla combination. Supported combinations: "
                f"{supported}."
            ) from exc

    if page_value is not None:
        return build_page_url(page_value, query=query)

    return build_search_url(_query_value(query))


def preview_liverpool_url(
    *,
    query: str | None = None,
    page: str | Page | None = None,
    category: str | Category | None = None,
    brand: Brand | str | None = None,
    talla: str | list[str] | tuple[str, ...] | None = None,
    url: str | None = None,
    show_plp: bool = False,
) -> str:
    """Return the final Liverpool URL for manual testing.

    Args:
        query: Optional Liverpool search query.
        page: Optional Liverpool page name or enum member.
        category: Legacy alias for ``page``.
        brand: Unsupported generated brand/facet selector.
        talla: Optional Zapatos-only Talla value(s).
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
        return build_page_url(page_value, show_plp=True)

    if not (query or page_value):
        raise ValueError("Provide query, page, category, or explicit url.")

    return build_liverpool_url(
        query=query,
        page=page_value,
        brand=brand,
        talla=talla,
    )


def build_zapatos_talla_url(
    talla: str | list[str] | tuple[str, ...],
    *,
    include_seller: bool = False,
) -> str:
    """Build a seeded Liverpool Zapatos Talla URL from documented fixtures."""
    talla_values = _normalize_talla_values(talla)
    if include_seller:
        mapping = _ZAPATOS_SELLER_TALLA_URLS
        label = "seller+talla"
    else:
        mapping = _ZAPATOS_TALLA_URLS
        label = "talla"
    try:
        return mapping[talla_values]
    except KeyError as exc:
        supported = ", ".join(" + ".join(combo) for combo in sorted(mapping))
        raise ValueError(
            f"Unsupported Liverpool Zapatos {label} combination. Supported combinations: "
            f"{supported}."
        ) from exc


def build_page_url(
    page: str | Page,
    *,
    query: str | None = None,
    show_plp: bool = False,
) -> str:
    """Build a verified Liverpool-seller URL for a documented page.

    Args:
        page: Known Liverpool page name or ``Page`` enum member.
        query: Optional page-scoped search query.
        show_plp: Whether to force ``?showPLP`` on the generated URL.

    Returns:
        A verified seller-filtered Liverpool listing URL.

    Notes:
        Page-scoped queries omit the category segment and use
        ``/tienda/N-{token}?s=query``. Category routes on Liverpool's Next.js
        App Router require the lowercase category ID segment
        (``/tienda/{category_id}/N-{token}``) and ``?showPLP`` on landing
        pages so SSR renders ``initialResults`` instead of promotional blocks.
    """
    page_value = resolve_page(page)
    metadata = page_value.value
    segment = _resolve_seller_filtered_segment(page_name=page_value.name)
    base_segment = segment.split("?", 1)[0]
    query_value = _query_value(query)
    if query_value:
        return f"{BASE_URL}/{base_segment}?s={urllib.parse.quote_plus(query_value)}"

    category_segment = metadata.category_id.lower()
    url = f"{BASE_URL}/{category_segment}/{base_segment}"
    if show_plp or metadata.kind is PageKind.landing:
        return f"{url}?showPLP"
    return url


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
