from __future__ import annotations

import hashlib
import logging
import re
from typing import Any
import unicodedata

from provider.amazon.motor import Amazon
from provider.amazon.options import Brand as AmazonBrand
from provider.amazon.options import Seller as AmazonSeller
from provider.amazon.urls import build_amazon_url
from provider.liverpool.motor import Liverpool
from provider.liverpool.options import Brand as LiverpoolBrand
from provider.liverpool.options import Page as LiverpoolPage
from provider.liverpool.urls import build_liverpool_url
from provider.mercado_libre.motor import MercadoLibre
from provider.mercado_libre.options import Category as MercadoLibreCategory
from provider.mercado_libre.options import Seller as MercadoLibreSeller
from provider.mercado_libre.options import State as MercadoLibreState
from provider.mercado_libre.urls import build_mercado_libre_url
from provider.palacio_de_hierro.motor import PalacioDeHierro
from provider.palacio_de_hierro.options import Page as PalacioPage
from provider.palacio_de_hierro.urls import build_palacio_url

from .registry import MotorRegistry

logger = logging.getLogger(__name__)


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


def _storage_path(provider: str, job_id: str, qualifier: str = "") -> str:
    """
    Build a relative storage path such as:
        "mercado_libre/zelda-wii.json"
        "mercado_libre/nintendo-ds__consolas.json"
        "amazon/iphone__amazon-mx.json"
        "liverpool/lv-laptops.json"
    """
    name = _slug(job_id)
    if qualifier:
        name = f"{name}__{_slug(qualifier)}"
    return f"{provider}/{name}.json"


def _explicit_url(url: str | None) -> str | None:
    """Return a stripped explicit URL when one is configured."""
    if url is None:
        return None
    value = str(url).strip()
    return value or None


def _attach_search_metadata(
    motor: Any,
    *,
    query_text: str | None = None,
    filter_config: dict[str, Any] | None = None,
) -> Any:
    """Attach structured query and filter metadata to a constructed motor and its catalog."""
    cleaned_filters = (
        {
            k: v
            for k, v in filter_config.items()
            if v is not None and v != "" and v != [] and v != ()
        }
        if filter_config
        else None
    )
    if hasattr(motor, "query_text"):
        motor.query_text = query_text
    if hasattr(motor, "filter_config"):
        motor.filter_config = cleaned_filters
    catalog = getattr(motor, "catalog", None)
    if catalog is not None and hasattr(motor, "job_id") and hasattr(motor, "storage_path"):
        catalog.register_search(
            job_id=motor.job_id,
            storage_path=motor.storage_path,
            resolved_url=getattr(motor, "url", None),
            query_text=query_text,
            filter_config=cleaned_filters,
            is_enabled=True,
        )
    return motor


def _ml_factory(
    job_id: str,
    url: str | None = None,
    query: str | None = None,
    seller: MercadoLibreSeller | None = None,
    category: MercadoLibreCategory | None = None,
    state: MercadoLibreState | None = None,
    **_,
) -> MercadoLibre:
    """
    Mercado Libre jobs use an explicit URL when provided, otherwise they build
    global or known-seller listing URLs from provider-specific structured fields.

    Examples:
        job_id="zelda wii"                          → mercado_libre/zelda-wii.json
        job_id="nintendo ds", category=consolas     → mercado_libre/nintendo-ds__consolas.json
    """
    explicit_url = _explicit_url(url)
    if explicit_url and (query or seller or category or state):
        logger.warning(
            "Mercado Libre job %r uses explicit url; ignoring query/seller/category/state "
            "filters. Remove 'url' to use structured Mercado Libre search fields.",
            job_id,
        )
    if explicit_url:
        path = _storage_path("mercado_libre", job_id)
        return _attach_search_metadata(
            MercadoLibre(job_id, explicit_url, storage_path=path),
            filter_config={"explicit_url": True},
        )

    url = build_mercado_libre_url(
        query=query,
        seller=seller,
        category=category,
        state=state,
    )

    qualifier = "-".join(option.name for option in (seller, category, state) if option is not None)
    path = _storage_path("mercado_libre", job_id, qualifier)
    return _attach_search_metadata(
        MercadoLibre(job_id, url, storage_path=path),
        query_text=query,
        filter_config={
            "seller": seller.name if seller is not None else None,
            "category": category.name if category is not None else None,
            "state": state.name if state is not None else None,
        },
    )


def _az_factory(
    job_id: str,
    url: str | None = None,
    query: str | None = None,
    seller: AmazonSeller = AmazonSeller.none,
    brand: AmazonBrand | None = None,
    **_,
) -> Amazon:
    """
    Amazon jobs use an explicit URL when provided, otherwise they build search
    URLs from Amazon-specific query and refinement fields.

    Examples:
        job_id="amiibo", query="amiibo"                  → amazon/amiibo.json
        job_id="iphone", query="iphone", seller=amazon_mx
                                                    → amazon/iphone__amazon-mx.json
        job_id="UGREEN store", seller=ugreen_group_limited
                                           → amazon/ugreen-store__ugreen-group-limited.json
        job_id="apple", query="apple", brand=apple       → amazon/apple__apple.json
    """
    explicit_url = _explicit_url(url)
    if explicit_url and (query or seller != AmazonSeller.none or brand):
        logger.warning(
            "Amazon job %r uses explicit url; ignoring query/seller/brand filters. "
            "Remove 'url' to use structured Amazon search fields.",
            job_id,
        )
    if explicit_url:
        path = _storage_path("amazon", job_id)
        return _attach_search_metadata(
            Amazon(job_id, explicit_url, storage_path=path),
            filter_config={"explicit_url": True},
        )

    url = build_amazon_url(
        query=query,
        seller=seller,
        brand=brand,
    )

    qualifier = "-".join(
        option.name
        for option in (seller if seller != AmazonSeller.none else None, brand)
        if option is not None
    )
    path = _storage_path("amazon", job_id, qualifier)
    return _attach_search_metadata(
        Amazon(job_id, url, storage_path=path),
        query_text=query,
        filter_config={
            "seller": seller.name if seller != AmazonSeller.none else None,
            "brand": brand.name if brand is not None else None,
        },
    )


def _lv_factory(
    job_id: str,
    url: str | None = None,
    query: str | None = None,
    page: LiverpoolPage | None = None,
    category: LiverpoolPage | None = None,
    brand: LiverpoolBrand | str | None = None,
    talla: str | list[str] | tuple[str, ...] | None = None,
    **_,
) -> Liverpool:
    """
    Liverpool jobs use an explicit URL when provided, otherwise the URL is
    generated from Liverpool-specific job fields and constrained to Liverpool
    as seller.

    Example:
        job_id="LV Laptops"  →  liverpool/lv-laptops.json
    """
    explicit_url = _explicit_url(url)
    if explicit_url and (query or page or category or brand or talla):
        logger.warning(
            "Liverpool job %r uses explicit url; ignoring page/category/query/brand/talla "
            "filters. "
            "Remove 'url' to use structured Liverpool search fields.",
            job_id,
        )
    if explicit_url:
        path = _storage_path("liverpool", job_id)
        return _attach_search_metadata(
            Liverpool(job_id, explicit_url, storage_path=path),
            filter_config={"explicit_url": True},
        )

    url = build_liverpool_url(
        query=query,
        page=page,
        category=category,
        brand=brand,
        talla=talla,
    )

    path = _storage_path("liverpool", job_id)
    resolved_page = page or category
    return _attach_search_metadata(
        Liverpool(job_id, url, storage_path=path),
        query_text=query,
        filter_config={
            "page": (
                resolved_page.name if isinstance(resolved_page, LiverpoolPage) else resolved_page
            ),
            "brand": brand.name if isinstance(brand, LiverpoolBrand) else brand,
            "talla": list(talla) if isinstance(talla, (list, tuple)) else talla,
        },
    )


def _ph_factory(
    job_id: str,
    url: str | None = None,
    query: str | None = None,
    page: PalacioPage | None = None,
    brands: str | list[str] | tuple[str, ...] | None = None,
    **_,
) -> PalacioDeHierro:
    """
    Palacio jobs use an explicit URL when provided, otherwise the URL is
    generated from Palacio-specific page, brand, or global search fields.

    Example:
        job_id="PH Macbook Air"  →  palacio_de_hierro/ph-macbook-air.json
    """
    explicit_url = _explicit_url(url)
    if explicit_url and (query or page or brands):
        logger.warning(
            "Palacio job %r uses explicit url; ignoring page/query/brands filters. "
            "Remove 'url' to use structured Palacio search fields.",
            job_id,
        )
    if explicit_url:
        path = _storage_path("palacio_de_hierro", job_id)
        return _attach_search_metadata(
            PalacioDeHierro(job_id, explicit_url, storage_path=path),
            filter_config={"explicit_url": True},
        )

    url = build_palacio_url(
        query=query,
        page=page,
        brands=brands,
    )

    path = _storage_path("palacio_de_hierro", job_id)
    return _attach_search_metadata(
        PalacioDeHierro(job_id, url, storage_path=path),
        query_text=query,
        filter_config={
            "page": page.name if isinstance(page, PalacioPage) else page,
            "brands": list(brands) if isinstance(brands, (list, tuple)) else brands,
        },
    )


def register_default_factories(registry: MotorRegistry) -> None:
    registry.factory("ml")(_ml_factory)
    registry.factory("az")(_az_factory)
    registry.factory("lv")(_lv_factory)
    registry.factory("ph")(_ph_factory)
