"""Palacio de Hierro page metadata and configuration lookups."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import Enum


@dataclass(frozen=True)
class PalacioPage:
    """Documented Palacio de Hierro listing page metadata.

    Args:
        display_name: Storefront label used in Palacio navigation.
        path: URL path segments required to open the listing page.
        breadcrumb: Known storefront hierarchy for the listing page.
        aliases: Extra labels accepted in YAML job configuration.
    """

    display_name: str
    path: tuple[str, ...]
    breadcrumb: tuple[str, ...]
    aliases: tuple[str, ...] = ()


class Page(Enum):
    """Palacio pages that can be referenced from ``config/jobs.yaml``."""

    electronica = PalacioPage(
        display_name="Electronica",
        path=("electronica",),
        breadcrumb=("Electronica",),
        aliases=("Electrónica",),
    )
    tablets = PalacioPage(
        display_name="iPad y Tablet",
        path=("electronica", "tablets"),
        breadcrumb=("Electronica", "iPad y Tablet"),
        aliases=("ipad tablet", "IPAD Y TABLET"),
    )
    computo = PalacioPage(
        display_name="Computo",
        path=("electronica", "computadoras"),
        breadcrumb=("Electronica", "Computo"),
        aliases=("Cómputo", "computadoras"),
    )
    laptops = PalacioPage(
        display_name="Laptops",
        path=("electronica", "computadoras", "laptops"),
        breadcrumb=("Electronica", "Computo", "Laptops"),
        aliases=("computadoras laptops",),
    )
    electrodomesticos = PalacioPage(
        display_name="Electrodomesticos",
        path=("hogar", "electrodomesticos"),
        breadcrumb=("Hogar", "Electrodomesticos"),
        aliases=("Electrodomésticos", "hogar electrodomesticos"),
    )
    linea_blanca = PalacioPage(
        display_name="Linea Blanca",
        path=("hogar", "linea-blanca"),
        breadcrumb=("Hogar", "Linea Blanca"),
        aliases=("Línea Blanca",),
    )
    refrigeradores = PalacioPage(
        display_name="Refrigeradores",
        path=("hogar", "linea-blanca", "refrigeradores"),
        breadcrumb=("Hogar", "Linea Blanca", "Refrigeradores"),
        aliases=("linea blanca refrigeradores",),
    )
    videojuegos = PalacioPage(
        display_name="Videojuegos",
        path=("videojuegos",),
        breadcrumb=("Videojuegos",),
    )
    nintendo = PalacioPage(
        display_name="Nintendo",
        path=("videojuegos", "nintendo"),
        breadcrumb=("Videojuegos", "Nintendo"),
        aliases=("videojuegos nintendo",),
    )
    playstation = PalacioPage(
        display_name="PlayStation",
        path=("videojuegos", "playstation"),
        breadcrumb=("Videojuegos", "PlayStation"),
        aliases=("videojuegos playstation",),
    )


def normalize_page_key(text: str) -> str:
    """Normalize Palacio page labels for tolerant configuration lookup.

    Args:
        text: Enum key, display label, path label, or configured alias.

    Returns:
        Lowercase ASCII words separated by single spaces.
    """
    normalized = unicodedata.normalize("NFKD", text or "")
    normalized = normalized.encode("ascii", "ignore").decode("ascii")
    normalized = normalized.casefold()
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def valid_page_keys() -> str:
    """Return supported Palacio page enum keys for validation messages."""
    return ", ".join(page.name for page in Page)


def resolve_page(value: str | Page) -> Page:
    """Resolve a Palacio page from an enum member or configuration string.

    Args:
        value: Page enum member, enum key, storefront label, or alias.

    Returns:
        Matching Palacio page enum member.

    Raises:
        ValueError: If the value is blank, unknown, or ambiguous.
    """
    if isinstance(value, Page):
        return value

    raw = str(value or "").strip()
    if not raw:
        raise ValueError("Palacio page cannot be blank.")

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
            f"Ambiguous Palacio page {raw!r}. Use one of these page keys: {candidates}."
        )

    raise ValueError(f"Unknown Palacio page {raw!r}. Valid values: {valid_page_keys()}.")


def _aliases_for(page: Page) -> tuple[str, ...]:
    metadata = page.value
    return (
        page.name,
        metadata.display_name,
        " ".join(metadata.path),
        "/".join(metadata.path),
        " > ".join(metadata.breadcrumb),
        *metadata.aliases,
    )


def _build_page_lookup() -> dict[str, set[Page]]:
    lookup: dict[str, set[Page]] = {}
    for page in Page:
        for alias in _aliases_for(page):
            lookup.setdefault(normalize_page_key(alias), set()).add(page)
    return lookup


_PAGE_LOOKUP = _build_page_lookup()
