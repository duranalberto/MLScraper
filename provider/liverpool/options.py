from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import Enum

LIVERPOOL_SELLER_REFINEMENT_NAME = "variants.sellernames"
LIVERPOOL_SELLER_REFINEMENT_VALUE = "liverpool"


class PageKind(Enum):
    """Known Liverpool page roles."""

    landing = "landing"
    products = "products"


@dataclass(frozen=True)
class LiverpoolPage:
    """Documented Liverpool page metadata.

    Args:
        display_name: Canonical page name from Liverpool breadcrumbs.
        kind: Whether the page is primarily a landing page or product listing.
        breadcrumb: Full Liverpool hierarchy beginning with ``Home``.
        slug: Human-readable URL slug used by Liverpool.
        category_id: Liverpool category id from breadcrumbs and canonical URLs.
        canonical_url: Unfiltered canonical Liverpool page URL.
        aliases: Extra labels accepted for YAML configuration and previews.
    """

    display_name: str
    kind: PageKind
    breadcrumb: tuple[str, ...]
    slug: str
    category_id: str
    canonical_url: str
    aliases: tuple[str, ...] = ()


class Page(Enum):
    """Liverpool pages that can be referenced from ``config/jobs.yaml``."""

    linea_blanca_y_electrodomesticos = LiverpoolPage(
        display_name="Línea Blanca y Electrodomésticos",
        kind=PageKind.landing,
        breadcrumb=("Home", "Línea Blanca y Electrodomésticos"),
        slug="línea-blanca-y-electrodomésticos",
        category_id="CATST42832389",
        canonical_url=(
            "https://www.liverpool.com.mx/tienda/"
            "l%C3%ADnea-blanca-y-electrodom%C3%A9sticos/catst42832389"
        ),
    )
    electrodomesticos_de_cocina = LiverpoolPage(
        display_name="Electrodomésticos de Cocina",
        kind=PageKind.landing,
        breadcrumb=(
            "Home",
            "Línea Blanca y Electrodomésticos",
            "Electrodomésticos de Cocina",
        ),
        slug="electrodomésticos-de-cocina",
        category_id="CATST42832953",
        canonical_url=(
            "https://www.liverpool.com.mx/tienda/"
            "electrodom%C3%A9sticos-de-cocina/catst42832953"
        ),
    )
    cafeteras_y_molinos = LiverpoolPage(
        display_name="Cafeteras y Molinos",
        kind=PageKind.products,
        breadcrumb=(
            "Home",
            "Línea Blanca y Electrodomésticos",
            "Electrodomésticos de Cocina",
            "Cafeteras y Molinos",
        ),
        slug="cafeteras-y-molinos",
        category_id="CATST42843585",
        canonical_url=(
            "https://www.liverpool.com.mx/tienda/"
            "cafeteras-y-molinos/catst42843585"
        ),
    )
    licuadoras = LiverpoolPage(
        display_name="Licuadoras",
        kind=PageKind.products,
        breadcrumb=(
            "Home",
            "Línea Blanca y Electrodomésticos",
            "Electrodomésticos de Cocina",
            "Licuadoras",
        ),
        slug="licuadoras",
        category_id="CATST42843581",
        canonical_url="https://www.liverpool.com.mx/tienda/licuadoras/catst42843581",
    )
    freidoras = LiverpoolPage(
        display_name="Freidoras",
        kind=PageKind.products,
        breadcrumb=(
            "Home",
            "Línea Blanca y Electrodomésticos",
            "Electrodomésticos de Cocina",
            "Freidoras",
        ),
        slug="freidoras",
        category_id="CATST42843539",
        canonical_url="https://www.liverpool.com.mx/tienda/freidoras/catst42843539",
    )
    hornos_de_microondas = LiverpoolPage(
        display_name="Hornos de Microondas",
        kind=PageKind.products,
        breadcrumb=(
            "Home",
            "Línea Blanca y Electrodomésticos",
            "Electrodomésticos de Cocina",
            "Hornos de Microondas",
        ),
        slug="hornos-de-microondas",
        category_id="CATST42843550",
        canonical_url=(
            "https://www.liverpool.com.mx/tienda/"
            "hornos-de-microondas/catst42843550"
        ),
    )
    hornos_electricos = LiverpoolPage(
        display_name="Hornos Eléctricos",
        kind=PageKind.products,
        breadcrumb=(
            "Home",
            "Línea Blanca y Electrodomésticos",
            "Electrodomésticos de Cocina",
            "Hornos Eléctricos",
        ),
        slug="hornos-eléctricos",
        category_id="CATST53843927",
        canonical_url=(
            "https://www.liverpool.com.mx/tienda/"
            "hornos-el%C3%A9ctricos/catst53843927"
        ),
        aliases=("Hornos eléctricos",),
    )
    computacion = LiverpoolPage(
        display_name="Computación",
        kind=PageKind.landing,
        breadcrumb=("Home", "Electrónica", "Computación"),
        slug="computación",
        category_id="CAT3410055",
        canonical_url=(
            "https://www.liverpool.com.mx/tienda/"
            "computaci%C3%B3n/cat3410055"
        ),
    )
    laptops = LiverpoolPage(
        display_name="Laptops",
        kind=PageKind.products,
        breadcrumb=("Home", "Electrónica", "Computación", "Laptops"),
        slug="laptops",
        category_id="CATST10075558",
        canonical_url="https://www.liverpool.com.mx/tienda/laptops/catst10075558",
    )
    tablets = LiverpoolPage(
        display_name="Tablets",
        kind=PageKind.products,
        breadcrumb=("Home", "Electrónica", "Computación", "Tablets"),
        slug="tablets",
        category_id="CAT580066",
        canonical_url="https://www.liverpool.com.mx/tienda/tablets/cat580066",
    )
    accesorios_computacion = LiverpoolPage(
        display_name="Accesorios Computación",
        kind=PageKind.products,
        breadcrumb=("Home", "Electrónica", "Computación", "Accesorios Computación"),
        slug="accesorios-computación",
        category_id="CAT670053",
        canonical_url=(
            "https://www.liverpool.com.mx/tienda/"
            "accesorios-computaci%C3%B3n/cat670053"
        ),
    )
    videojuegos = LiverpoolPage(
        display_name="Videojuegos",
        kind=PageKind.landing,
        breadcrumb=("Home", "Videojuegos"),
        slug="videojuegos",
        category_id="CAT670055",
        canonical_url="https://www.liverpool.com.mx/tienda/videojuegos/cat670055",
    )
    nintendo = LiverpoolPage(
        display_name="Nintendo",
        kind=PageKind.landing,
        breadcrumb=("Home", "Videojuegos", "Nintendo"),
        slug="nintendo",
        category_id="CAT5030010",
        canonical_url="https://www.liverpool.com.mx/tienda/nintendo/cat5030010",
        aliases=("Consolas y videojuegos Nintendo",),
    )
    consolas_nintendo = LiverpoolPage(
        display_name="Consolas Nintendo",
        kind=PageKind.products,
        breadcrumb=("Home", "Videojuegos", "Nintendo", "Consolas Nintendo"),
        slug="consolas-nintendo",
        category_id="CATST16854843",
        canonical_url=(
            "https://www.liverpool.com.mx/tienda/"
            "consolas-nintendo/catst16854843"
        ),
    )
    juegos_nintendo = LiverpoolPage(
        display_name="Juegos Nintendo",
        kind=PageKind.products,
        breadcrumb=("Home", "Videojuegos", "Nintendo", "Juegos Nintendo"),
        slug="juegos-nintendo",
        category_id="CATST14539980",
        canonical_url="https://www.liverpool.com.mx/tienda/juegos-nintendo/catst14539980",
    )
    controles_nintendo = LiverpoolPage(
        display_name="Controles Nintendo",
        kind=PageKind.products,
        breadcrumb=("Home", "Videojuegos", "Nintendo", "Controles Nintendo"),
        slug="controles-nintendo",
        category_id="CATST20605695",
        canonical_url=(
            "https://www.liverpool.com.mx/tienda/"
            "controles-nintendo/catst20605695"
        ),
    )
    apple = LiverpoolPage(
        display_name="Apple",
        kind=PageKind.landing,
        breadcrumb=("Home", "Apple"),
        slug="apple",
        category_id="CATST2145072",
        canonical_url="https://www.liverpool.com.mx/tienda/apple/catst2145072",
    )


# Compatibility alias: older Liverpool jobs used `category`; it now means a page.
Category = Page


class Brand(Enum):
    """Deprecated Liverpool brand selector names.

    Brand generation is intentionally unsupported for seller-only URLs. These
    values are kept only so explicit-URL jobs can continue to ignore legacy
    structured fields without breaking imports.
    """

    lg = "LG"


def normalize_page_key(text: str) -> str:
    """Normalize Liverpool page labels for lookup and path comparisons."""
    normalized = unicodedata.normalize("NFKD", text or "")
    normalized = normalized.encode("ascii", "ignore").decode("ascii")
    normalized = normalized.casefold()
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def valid_page_keys() -> str:
    """Return a comma-separated list of supported Liverpool page enum keys."""
    return ", ".join(page.name for page in Page)


def resolve_page(value: str | Page) -> Page:
    """Resolve a Liverpool page from an enum key, display name, id, or alias.

    Args:
        value: Page enum member or user-facing page label.

    Returns:
        The matching ``Page`` enum member.

    Raises:
        ValueError: If the value is blank, unknown, or ambiguous.
    """
    if isinstance(value, Page):
        return value

    raw = str(value or "").strip()
    if not raw:
        raise ValueError("Liverpool page cannot be blank.")

    try:
        return Page[raw]
    except KeyError:
        pass

    key = normalize_page_key(raw)
    matches = _PAGE_LOOKUP.get(key, set())
    if len(matches) == 1:
        return next(iter(matches))
    if matches:
        candidates = ", ".join(sorted(page.name for page in matches))
        raise ValueError(
            f"Ambiguous Liverpool page {raw!r}. Use one of these page keys: {candidates}."
        )

    raise ValueError(f"Unknown Liverpool page {raw!r}. Valid values: {valid_page_keys()}.")


def resolve_page_path(*breadcrumb: str) -> Page:
    """Resolve a page only when a full documented Liverpool breadcrumb matches.

    Args:
        *breadcrumb: Breadcrumb segments, with or without the leading ``Home``.

    Returns:
        The page whose full hierarchy matches the provided segments.

    Raises:
        ValueError: If the path is blank or does not match a documented page.
    """
    parts = tuple(part.strip() for part in breadcrumb if str(part or "").strip())
    if not parts:
        raise ValueError("Liverpool page path cannot be blank.")

    normalized = tuple(normalize_page_key(part) for part in parts)
    for page in Page:
        page_path = tuple(normalize_page_key(part) for part in page.value.breadcrumb)
        if normalized == page_path or normalized == page_path[1:]:
            return page

    path = " > ".join(parts)
    raise ValueError(f"Unknown Liverpool page path {path!r}.")


def seller_pages() -> tuple[Page, ...]:
    """Return pages that can request Liverpool-seller URL resolution."""
    return tuple(Page)


def _aliases_for(page: Page) -> tuple[str, ...]:
    value = page.value
    return (
        page.name,
        value.display_name,
        value.category_id,
        value.category_id.lower(),
        *value.aliases,
    )


def _build_page_lookup() -> dict[str, set[Page]]:
    lookup: dict[str, set[Page]] = {}
    for page in Page:
        for alias in _aliases_for(page):
            lookup.setdefault(normalize_page_key(alias), set()).add(page)
    return lookup


_PAGE_LOOKUP = _build_page_lookup()
