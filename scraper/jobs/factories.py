from __future__ import annotations

import hashlib
import re
import unicodedata

from provider.amazon.motor import Amazon
from provider.amazon.options import Seller
from provider.liverpool.motor import Liverpool
from provider.mercado_libre.motor import MercadoLibre
from provider.mercado_libre.options import Category
from provider.palacio_de_hierro.motor import PalacioDeHierro

from .registry import MotorRegistry


def _slug(text: str) -> str:
    """
    Convert arbitrary text to a safe, lowercase, hyphen-separated slug.
    e.g. "Nintendo DS"  →  "nintendo-ds"
         "LV Laptops"   →  "lv-laptops"
         "pokémon tcg"  →  "pokemon-tcg"
    """
    source = text or ""
    text = unicodedata.normalize("NFKD", source)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    slug = re.sub(r"-+", "-", text).strip("-")
    if slug:
        return slug

    digest = hashlib.sha1(source.encode("utf-8")).hexdigest()[:8]
    return f"item-{digest}"


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


def _ml_factory(
    search_term: str,
    category: Category = Category.consolas_videojuegos,
    url: str | None = None,
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
        else category.name  # e.g. "consolas", "videojuegos", "deportes_jersey"
    )
    path = _storage_path("mercado_libre", search_term, qualifier)
    return MercadoLibre(search_term, category, url=url, storage_path=path)


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


def _ph_factory(search_term: str, url: str, **_) -> PalacioDeHierro:
    """
    Same convention as Liverpool.

    Example:
        search_term="PH Macbook Air"  →  palacio_de_hierro/ph-macbook-air.json
    """
    path = _storage_path("palacio_de_hierro", search_term)
    return PalacioDeHierro(search_term, url, storage_path=path)


def register_default_factories(registry: MotorRegistry) -> None:
    registry.factory("ml")(_ml_factory)
    registry.factory("az")(_az_factory)
    registry.factory("lv")(_lv_factory)
    registry.factory("ph")(_ph_factory)
