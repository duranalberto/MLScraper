"""
provider/generator.py

Declarative Scraping Job Catalogue
────────────────────────────────────
All scraping jobs are expressed as plain dicts.  The only required key in
every entry is "provider", which maps to a registered factory (see
provider/factories.py).  Every other key is provider-specific and forwarded
verbatim to the factory.

How to read an entry
────────────────────
    {"provider": "ml", "search_term": "zelda wii"}
        → MercadoLibre("zelda wii")  (default category)

    {"provider": "ml", "search_term": "nintendo ds", "category": Category.consolas}
        → MercadoLibre("nintendo ds", Category.consolas)

    {"provider": "lv", "search_term": "LV Laptops", "url": "https://..."}
        → Liverpool("LV Laptops", "https://...")

    {"provider": "az", "search_term": "amiibo", "seller": Seller.amazon_mx}
        → Amazon("amiibo", Seller.amazon_mx)

    {"provider": "ph", "search_term": "PH Macbook Air", "url": "https://..."}
        → PalacioDeHierro("PH Macbook Air", "https://...")

Adding or removing a job
────────────────────────
Edit the list below.  No other file needs to change.

Adding a new provider
─────────────────────
1. Implement the Motor subclass.
2. Register its factory in provider/factories.py.
3. Add entries here using the new provider key.
"""

from provider.mercado_libre.utils import Category
from provider.amazon.utils import Seller
from provider.registry import build_motors, register_entries

# Factories must be imported so their @_REGISTRY.factory decorators run
import provider.factories  # noqa: F401  (side-effect import)

from scraper.motor import Motor


# ---------------------------------------------------------------------------
# Job Catalogue
# ---------------------------------------------------------------------------

_ENTRIES = [

    # ── MercadoLibre ────────────────────────────────────────────────────────
    {"provider": "ml", "search_term": "fire emblem"},
    {"provider": "ml", "search_term": "zelda wii"},
    {"provider": "ml", "search_term": "pokemon ds"},
    {"provider": "ml", "search_term": "nintendo ds",        "category": Category.consolas},
    {"provider": "ml", "search_term": "nintendo switch",    "category": Category.consolas},
    {"provider": "ml", "search_term": "lote nintendo"},
    {"provider": "ml", "search_term": "atlas",              "category": Category.deportes_jersey},
    {"provider": "ml", "search_term": "game cube",          "category": Category.consolas},
    {"provider": "ml", "search_term": "game cube juegos"},

    # ── Liverpool ───────────────────────────────────────────────────────────
    {
        "provider": "lv",
        "search_term": "Laptops",
        "url": "https://www.liverpool.com.mx/tienda/Laptops/N-Z6GQrU4fZmxjTFXt9XTtjADb51HPoq41uykVTx%2F8p7q4Lv5kmJ%2FB7n9SHDZAiZOr",
    },
    {
        "provider": "lv",
        "search_term": "Juegos Nintendo",
        "url": "https://www.liverpool.com.mx/tienda/Juegos/N-Z6GQrU4fZmxjTFXt9XTtjEMtiDHLusAuxLK0y30fWRU5PhnhiYjJElHuz9EseRgf",
    },

    # ── Palacio de Hierro ───────────────────────────────────────────────────
    {
        "provider": "ph",
        "search_term": "Macbook",
        "url": "https://www.elpalaciodehierro.com/buscar?q=macbook",
    },

    # ── Amazon (examples — uncomment to activate) ───────────────────────────
    {"provider": "az", "search_term": "macbook",      "seller": Seller.amazon_mx},
    {"provider": "az", "search_term": "mac studio",      "seller": Seller.amazon_mx},
    # {"provider": "az", "search_term": "pokemon tcg", "seller": Seller.amazon_mx},
    # {"provider": "az", "search_term": "iphone",      "seller": Seller.amazon_remates},

]


# ---------------------------------------------------------------------------
# Public API  (consumed by scrapper.py)
# ---------------------------------------------------------------------------

def get_motors() -> list[Motor]:
    """Materialise every catalogue entry into a Motor instance."""
    register_entries(_ENTRIES)
    return build_motors()