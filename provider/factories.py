"""
provider/factories.py

Provider Factories + Storage Path Strategy
───────────────────────────────────────────
Each factory is the single place that knows:
  1. How to construct a Motor (which args, which class).
  2. What the canonical storage path for that job should be.

Storage path rules
──────────────────
Pattern:  <provider>/<slug>[__<qualifier>].json

• <provider>   — short provider identifier ("mercado_libre", "amazon", …)
• <slug>       — URL-safe, lowercase, hyphen-separated search term
• <qualifier>  — optional suffix that makes jobs with the same search_term
                 but different filters distinguishable, e.g.:
                   ml: category name  →  nintendo-ds__consolas.json
                   az: seller name    →  iphone__amazon-mx.json
                 Jobs with no filter get no qualifier:
                   ml "amiibo" (default category) → amiibo.json

This ensures:
  • No flat-root collisions — each provider has its own sub-directory.
  • No same-term/different-filter collisions — qualifier encodes the filter.
  • Filenames are human-readable without opening the file.
  • No UUID / hash tricks needed.
"""

from __future__ import annotations

import re
import unicodedata

from provider.registry import _REGISTRY
from provider.amazon.motor import Amazon
from provider.amazon.utils import Seller
from provider.liverpool.motor import Liverpool
from provider.mercado_libre.motor import MercadoLibre
from provider.mercado_libre.utils import Category
from provider.palacio_de_hierro.motor import PalacioDeHierro


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _slug(text: str) -> str:
    """
    Convert arbitrary text to a safe, lowercase, hyphen-separated slug.
    e.g. "Nintendo DS"  →  "nintendo-ds"
         "LV Laptops"   →  "lv-laptops"
         "pokémon tcg"  →  "pokemon-tcg"
    """
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return re.sub(r"-+", "-", text).strip("-")


def _storage_path(provider: str, search_term: str, qualifier: str = "") -> str:
    """
    Build a relative storage path such as:
        "mercado_libre/zelda-wii.json"
        "mercado_libre/nintendo-ds__consolas.json"
        "amazon/iphone__amazon-mx.json"
        "liverpool/lv-laptops.json"
    """
    name = _slug(search_term)
    if qualifier:
        name = f"{name}__{_slug(qualifier)}"
    return f"{provider}/{name}.json"


# ---------------------------------------------------------------------------
# MercadoLibre
# ---------------------------------------------------------------------------

@_REGISTRY.factory("ml")
def _ml_factory(
    search_term: str,
    category: Category = Category.consolas_videojuegos,
    **_,
) -> MercadoLibre:
    """
    Qualifier: category name when it is not the default, otherwise omitted.

    Examples:
        search_term="zelda wii"                          → mercado_libre/zelda-wii.json
        search_term="nintendo ds", category=consolas     → mercado_libre/nintendo-ds__consolas.json
        search_term="nintendo ds", category=videojuegos  → mercado_libre/nintendo-ds__videojuegos.json
    """
    qualifier = (
        ""
        if category == Category.consolas_videojuegos
        else category.name          # e.g. "consolas", "videojuegos", "deportes_jersey"
    )
    path = _storage_path("mercado_libre", search_term, qualifier)
    return MercadoLibre(search_term, category, storage_path=path)


# ---------------------------------------------------------------------------
# Amazon
# ---------------------------------------------------------------------------

@_REGISTRY.factory("az")
def _az_factory(
    search_term: str,
    seller: Seller = Seller.none,
    **_,
) -> Amazon:
    """
    Qualifier: seller name when set, otherwise omitted.

    Examples:
        search_term="amiibo"                             → amazon/amiibo.json
        search_term="iphone", seller=amazon_mx           → amazon/iphone__amazon-mx.json
        search_term="iphone", seller=amazon_remates      → amazon/iphone__amazon-remates.json
    """
    qualifier = "" if seller == Seller.none else seller.name
    path = _storage_path("amazon", search_term, qualifier)
    return Amazon(search_term, seller, storage_path=path)


# ---------------------------------------------------------------------------
# Liverpool
# ---------------------------------------------------------------------------

@_REGISTRY.factory("lv")
def _lv_factory(search_term: str, url: str, **_) -> Liverpool:
    """
    Liverpool jobs are always identified by their explicit search_term label
    (e.g. "LV Laptops") which is already unique by convention.
    No qualifier needed.

    Example:
        search_term="LV Laptops"  →  liverpool/lv-laptops.json
    """
    path = _storage_path("liverpool", search_term)
    return Liverpool(search_term, url, storage_path=path)


# ---------------------------------------------------------------------------
# Palacio de Hierro
# ---------------------------------------------------------------------------

@_REGISTRY.factory("ph")
def _ph_factory(search_term: str, url: str, **_) -> PalacioDeHierro:
    """
    Same convention as Liverpool.

    Example:
        search_term="PH Macbook Air"  →  palacio_de_hierro/ph-macbook-air.json
    """
    path = _storage_path("palacio_de_hierro", search_term)
    return PalacioDeHierro(search_term, url, storage_path=path)