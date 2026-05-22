"""Mercado Libre category, seller, and listing state metadata."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class State(Enum):
    """Mercado Libre product conditions supported in generated URLs."""

    nuevo = "nuevo"
    usado = "usado"


@dataclass(frozen=True)
class MercadoLibreCategory:
    """Documented Mercado Libre category route metadata.

    Args:
        display_name: Category label shown by Mercado Libre.
        path: Full category path from the listing root.
        breadcrumb: Known category hierarchy for the route.
    """

    display_name: str
    path: tuple[str, ...]
    breadcrumb: tuple[str, ...]


class Category(Enum):
    """Mercado Libre categories that can be referenced from job configuration."""

    computacion = MercadoLibreCategory(
        display_name="Computacion",
        path=("computacion",),
        breadcrumb=("Computacion",),
    )
    celulares_telefonia = MercadoLibreCategory(
        display_name="Celulares y Telefonia",
        path=("celulares-telefonia",),
        breadcrumb=("Celulares y Telefonia",),
    )
    consolas_videojuegos = MercadoLibreCategory(
        display_name="Consolas y Videojuegos",
        path=("consolas-videojuegos",),
        breadcrumb=("Consolas y Videojuegos",),
    )
    consolas = MercadoLibreCategory(
        display_name="Consolas",
        path=("consolas-videojuegos", "consolas"),
        breadcrumb=("Consolas y Videojuegos", "Consolas"),
    )
    videojuegos = MercadoLibreCategory(
        display_name="Videojuegos",
        path=("consolas-videojuegos", "videojuegos"),
        breadcrumb=("Consolas y Videojuegos", "Videojuegos"),
    )


@dataclass(frozen=True)
class MercadoLibreSeller:
    """Known Mercado Libre seller storefront metadata.

    Args:
        display_name: Seller name shown on the storefront.
        landing_url: Store landing page kept for manual reference.
        listing_path: Full product listing path from Mercado Libre's listing
            domain.
    """

    display_name: str
    landing_url: str
    listing_path: tuple[str, ...]


class Seller(Enum):
    """Mercado Libre seller storefronts supported by generated URLs."""

    apple = MercadoLibreSeller(
        display_name="Apple",
        landing_url="https://www.mercadolibre.com.mx/tienda/apple",
        listing_path=("tienda", "apple"),
    )
    nintendo = MercadoLibreSeller(
        display_name="Nintendo",
        landing_url="https://www.mercadolibre.com.mx/tienda/nintendo",
        listing_path=("tienda", "nintendo"),
    )
