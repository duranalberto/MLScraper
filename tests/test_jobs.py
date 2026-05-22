from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

from provider.amazon.options import Brand as AmazonBrand
from provider.amazon.options import Seller
from provider.liverpool import urls as lv_urls
from provider.liverpool.options import (
    LIVERPOOL_SELLER_REFINEMENT_NAME,
    LIVERPOOL_SELLER_REFINEMENT_VALUE,
)
from provider.liverpool.options import Page as LiverpoolPage
from provider.mercado_libre.options import Category
from provider.mercado_libre.options import Seller as MercadoLibreSeller
from provider.mercado_libre.options import State
from provider.palacio_de_hierro.options import Page as PalacioPage
from scraper.jobs import factories
from scraper.jobs.loader import load_jobs
from scraper.jobs.registry import MotorRegistry
from tests.helpers import empty_article_storage


class JobLoaderTests(unittest.TestCase):
    def _write_jobs(self, content: str) -> Path:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        path = Path(tmpdir.name) / "jobs.yaml"
        path.write_text(content, encoding="utf-8")
        return path

    def test_load_jobs_coerces_enums_and_preserves_unknown_keys(self) -> None:
        path = self._write_jobs("""
jobs:
  - provider: ml
    job_id: " pokemon ds "
    category: consolas
    seller: nintendo
    state: usado
    custom: passthrough
  - provider: az
    job_id: macbook
    seller: amazon_mx
    brand: apple
  - provider: az
    job_id: ugreen
    seller: ugreen_group_limited
""")

        jobs = load_jobs(path)

        self.assertEqual(jobs[0]["job_id"], "pokemon ds")
        self.assertEqual(jobs[0]["category"], Category.consolas)
        self.assertEqual(jobs[0]["seller"], MercadoLibreSeller.nintendo)
        self.assertEqual(jobs[0]["state"], State.usado)
        self.assertEqual(jobs[0]["custom"], "passthrough")
        self.assertEqual(jobs[1]["seller"], Seller.amazon_mx)
        self.assertEqual(jobs[1]["brand"], AmazonBrand.apple)
        self.assertEqual(jobs[2]["seller"], Seller.ugreen_group_limited)

    def test_load_jobs_coerces_liverpool_page_and_ignores_seller(self) -> None:
        path = self._write_jobs("""
jobs:
  - provider: lv
    job_id: Hornos eléctricos Black
    query: black
    page: Hornos eléctricos
    seller: unsupported
""")

        with self.assertLogs("scraper.jobs.loader", level="WARNING") as logs:
            jobs = load_jobs(path)

        self.assertEqual(jobs[0]["page"], LiverpoolPage.hornos_electricos)
        self.assertNotIn("seller", jobs[0])
        self.assertIn("unsupported 'seller'", "\n".join(logs.output))

    def test_load_jobs_treats_liverpool_category_as_legacy_page_alias(self) -> None:
        path = self._write_jobs("""
jobs:
  - provider: lv
    job_id: Juegos Nintendo
    category: juegos_nintendo
""")

        jobs = load_jobs(path)

        self.assertEqual(jobs[0]["page"], LiverpoolPage.juegos_nintendo)
        self.assertNotIn("category", jobs[0])

    def test_load_jobs_skips_invalid_entries_without_short_circuiting(self) -> None:
        path = self._write_jobs("""
jobs:
  - not-a-mapping
  - provider: ml
  - provider: ml
    job_id: valid
    category: unknown
  - provider: ph
    job_id: invalid page
    page: missing
  - provider: lv
    job_id: ok
    url: https://example.test/list
""")

        jobs = load_jobs(path)

        self.assertEqual(
            jobs, [{"provider": "lv", "job_id": "ok", "url": "https://example.test/list"}]
        )

    def test_load_jobs_skips_unknown_amazon_brand(self) -> None:
        path = self._write_jobs("""
jobs:
  - provider: az
    job_id: bad brand
    brand: missing
""")

        self.assertEqual(load_jobs(path), [])

    def test_load_jobs_coerces_palacio_pages_and_brands_without_url(self) -> None:
        path = self._write_jobs("""
jobs:
  - provider: ph
    job_id: Computadoras Apple Asus
    page: Cómputo
    brands:
      - asus
      - apple
  - provider: ph
    job_id: Magic Keyboard
    query: magic keyboard
""")

        jobs = load_jobs(path)

        self.assertEqual(jobs[0]["page"], PalacioPage.computo)
        self.assertEqual(jobs[0]["brands"], ["asus", "apple"])
        self.assertEqual(
            jobs[1],
            {"provider": "ph", "job_id": "Magic Keyboard", "query": "magic keyboard"},
        )

    def test_load_jobs_skips_invalid_palacio_brands(self) -> None:
        path = self._write_jobs("""
jobs:
  - provider: ph
    job_id: bad brand
    page: computo
    brands:
      - apple
      - 15
""")

        self.assertEqual(load_jobs(path), [])

    def test_load_jobs_skips_unknown_liverpool_page_names(self) -> None:
        path = self._write_jobs("""
jobs:
  - provider: lv
    job_id: bad
    page: missing
  - provider: lv
    job_id: good
    page: Apple
""")

        jobs = load_jobs(path)

        self.assertEqual(jobs, [{"provider": "lv", "job_id": "good", "page": LiverpoolPage.apple}])

    def test_load_jobs_skips_conflicting_liverpool_page_and_category(self) -> None:
        path = self._write_jobs("""
jobs:
  - provider: lv
    job_id: conflict
    page: laptops
    category: tablets
""")

        jobs = load_jobs(path)

        self.assertEqual(jobs, [])

    def test_load_jobs_url_bypass_skips_provider_field_validation(self) -> None:
        path = self._write_jobs("""
jobs:
  - provider: ml
    job_id: ml bypass
    url: https://example.test/ml
    seller: missing
    category: unknown
    state: invalid
  - provider: az
    job_id: az bypass
    url: https://example.test/az
    seller: missing
    brand: unknown
  - provider: lv
    job_id: lv bypass
    url: https://example.test/lv
    page: missing
    category: also_missing
    seller: unsupported
  - provider: ph
    job_id: ph bypass
    url: https://example.test/ph
    page: missing
    brands:
      - apple
      - 15
""")

        jobs = load_jobs(path)

        self.assertEqual(
            jobs,
            [
                {
                    "provider": "ml",
                    "job_id": "ml bypass",
                    "url": "https://example.test/ml",
                    "seller": "missing",
                    "category": "unknown",
                    "state": "invalid",
                },
                {
                    "provider": "az",
                    "job_id": "az bypass",
                    "url": "https://example.test/az",
                    "seller": "missing",
                    "brand": "unknown",
                },
                {
                    "provider": "lv",
                    "job_id": "lv bypass",
                    "url": "https://example.test/lv",
                    "page": "missing",
                    "category": "also_missing",
                    "seller": "unsupported",
                },
                {
                    "provider": "ph",
                    "job_id": "ph bypass",
                    "url": "https://example.test/ph",
                    "page": "missing",
                    "brands": ["apple", 15],
                },
            ],
        )

    def test_load_jobs_url_bypass_allows_conflicting_liverpool_page_aliases(self) -> None:
        path = self._write_jobs("""
jobs:
  - provider: lv
    job_id: lv conflict bypass
    url: https://example.test/lv
    page: laptops
    category: tablets
""")

        jobs = load_jobs(path)

        self.assertEqual(
            jobs,
            [
                {
                    "provider": "lv",
                    "job_id": "lv conflict bypass",
                    "url": "https://example.test/lv",
                    "page": "laptops",
                    "category": "tablets",
                }
            ],
        )

    def test_load_jobs_handles_empty_jobs_list_and_rejects_bad_structure(self) -> None:
        empty_path = self._write_jobs("jobs:\n")
        missing_jobs_path = self._write_jobs("providers: []\n")
        non_list_path = self._write_jobs("jobs: {}\n")

        self.assertEqual(load_jobs(empty_path), [])
        with self.assertRaisesRegex(ValueError, "top-level 'jobs'"):
            load_jobs(missing_jobs_path)
        with self.assertRaisesRegex(ValueError, "must be a list"):
            load_jobs(non_list_path)

    def test_load_jobs_rejects_legacy_search_term_entries(self) -> None:
        path = self._write_jobs("""
jobs:
  - provider: az
    search_term: macbook
    query: macbook
""")

        with self.assertLogs("scraper.jobs.loader", level="WARNING") as logs:
            jobs = load_jobs(path)

        self.assertEqual(jobs, [])
        self.assertIn("legacy 'search_term'", "\n".join(logs.output))

    def test_load_jobs_skips_blank_job_id(self) -> None:
        path = self._write_jobs("""
jobs:
  - provider: az
    job_id: "   "
    query: macbook
""")

        self.assertEqual(load_jobs(path), [])

    def test_load_jobs_rejects_duplicate_provider_job_ids(self) -> None:
        path = self._write_jobs("""
jobs:
  - provider: az
    job_id: apple
    query: apple
  - provider: az
    job_id: apple
    seller: amazon_mx
""")

        with self.assertRaisesRegex(ValueError, "provider='az'.*job_id='apple'"):
            load_jobs(path)

    def test_load_jobs_allows_same_job_id_across_providers(self) -> None:
        path = self._write_jobs("""
jobs:
  - provider: lv
    job_id: Apple
    url: https://example.test/lv
  - provider: ph
    job_id: Apple
    url: https://example.test/ph
""")

        jobs = load_jobs(path)

        self.assertEqual([job["provider"] for job in jobs], ["lv", "ph"])


class FactoryTests(unittest.TestCase):
    class _MockResponse:
        def __init__(self, encrypted_url: str, page: LiverpoolPage | None = None) -> None:
            selected_navigation = []
            if page is not None:
                selected_navigation.append(
                    {
                        "name": "ancestors",
                        "refinements": [{"value": page.value.category_id}],
                    }
                )
            selected_navigation.append(
                {
                    "name": LIVERPOOL_SELLER_REFINEMENT_NAME,
                    "refinements": [{"value": LIVERPOOL_SELLER_REFINEMENT_VALUE}],
                }
            )
            self.payload = {
                "mainContent": {
                    "originalRequest": {"encryptedFullUrl": encrypted_url},
                    "selectedNavigation": selected_navigation,
                }
            }

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return self.payload

    def setUp(self) -> None:
        lv_urls._resolve_seller_filtered_segment.cache_clear()

    def tearDown(self) -> None:
        lv_urls._resolve_seller_filtered_segment.cache_clear()

    def _mock_liverpool_resolver(
        self,
        encrypted_url: str,
        page: LiverpoolPage | None = None,
    ):
        return patch(
            "provider.liverpool.urls.requests.get",
            return_value=self._MockResponse(encrypted_url, page),
        )

    def test_slug_normalizes_text_and_uses_digest_fallback_for_empty_slug(self) -> None:
        self.assertEqual(factories._slug("Pokémon TCG!!"), "pokemon-tcg")
        self.assertRegex(factories._slug("!!!"), r"^item-[0-9a-f]{8}$")

    def test_storage_path_adds_normalized_qualifier(self) -> None:
        self.assertEqual(
            factories._storage_path("amazon", "iPhone 15", "amazon_mx"),
            "amazon/iphone-15__amazon-mx.json",
        )

    def test_default_factories_build_expected_provider_storage_paths(self) -> None:
        registry = MotorRegistry()
        factories.register_default_factories(registry)
        registry.register_many(
            [
                {
                    "provider": "ml",
                    "job_id": "Nintendo DS",
                    "query": "Nintendo DS",
                    "category": Category.videojuegos,
                },
                {"provider": "az", "job_id": "iPhone", "seller": Seller.amazon_mx},
                {"provider": "lv", "job_id": "LV Laptops", "url": "https://example.test/lv"},
                {"provider": "ph", "job_id": "PH Apple", "url": "https://example.test/ph"},
            ]
        )

        with empty_article_storage():
            motors = registry.build()

        self.assertEqual(
            [motor.storage_path for motor in motors],
            [
                "mercado_libre/nintendo-ds__videojuegos.json",
                "amazon/iphone__amazon-mx.json",
                "liverpool/lv-laptops.json",
                "palacio_de_hierro/ph-apple.json",
            ],
        )

    def test_mercado_libre_factory_generates_global_urls_and_storage_variants(self) -> None:
        with empty_article_storage():
            plain_motor = factories._ml_factory("Nintendo 3DS", query="Nintendo 3DS")
            used_motor = factories._ml_factory(
                "Nintendo 3DS",
                query="Nintendo 3DS",
                category=Category.consolas_videojuegos,
                state=State.usado,
            )

        self.assertEqual(
            plain_motor.url,
            "https://listado.mercadolibre.com.mx/nintendo-3ds_NoIndex_True",
        )
        self.assertEqual(plain_motor.storage_path, "mercado_libre/nintendo-3ds.json")
        self.assertEqual(
            used_motor.url,
            "https://listado.mercadolibre.com.mx/"
            "consolas-videojuegos/usado/nintendo-3ds_NoIndex_True",
        )
        self.assertEqual(
            used_motor.storage_path,
            "mercado_libre/nintendo-3ds__consolas-videojuegos-usado.json",
        )

    def test_mercado_libre_factory_generates_known_store_url(self) -> None:
        with empty_article_storage():
            motor = factories._ml_factory(
                "Nintendo Videojuegos",
                seller=MercadoLibreSeller.nintendo,
                category=Category.videojuegos,
            )

        self.assertEqual(
            motor.url,
            "https://listado.mercadolibre.com.mx/"
            "tienda/nintendo/listado/consolas-videojuegos/videojuegos/",
        )
        self.assertEqual(
            motor.storage_path,
            "mercado_libre/nintendo-videojuegos__nintendo-videojuegos.json",
        )

    def test_mercado_libre_factory_explicit_url_wins_over_filters(self) -> None:
        with empty_article_storage():
            with self.assertLogs("scraper.jobs.factories", level="WARNING") as logs:
                motor = factories._ml_factory(
                    "Custom Mercado",
                    url="https://example.test/custom",
                    query="ignored",
                    seller=MercadoLibreSeller.apple,
                    category=Category.computacion,
                    state=State.nuevo,
                )

        self.assertEqual(motor.url, "https://example.test/custom")
        self.assertEqual(motor.storage_path, "mercado_libre/custom-mercado.json")
        self.assertIn("ignoring query/seller/category/state", "\n".join(logs.output))

    def test_amazon_factory_generates_filter_urls_and_storage_variants(self) -> None:
        with empty_article_storage():
            seller_motor = factories._az_factory("Apple", query="apple", seller=Seller.amazon_mx)
            brand_motor = factories._az_factory("Apple", query="apple", brand=AmazonBrand.apple)
            combined_motor = factories._az_factory(
                "Apple",
                query="apple",
                seller=Seller.amazon_mx,
                brand=AmazonBrand.apple,
            )
            catalogue_motor = factories._az_factory(
                "UGREEN catalogue",
                seller=Seller.ugreen_group_limited,
            )

        self.assertEqual(
            seller_motor.url,
            "https://www.amazon.com.mx/s?k=apple&rh=p_6%3AAVDBXBAVVSXLQ",
        )
        self.assertEqual(seller_motor.storage_path, "amazon/apple__amazon-mx.json")
        self.assertEqual(
            brand_motor.url,
            "https://www.amazon.com.mx/s?k=apple&rh=p_123%3A110955",
        )
        self.assertEqual(brand_motor.storage_path, "amazon/apple__apple.json")
        self.assertEqual(
            combined_motor.url,
            "https://www.amazon.com.mx/s?k=apple&rh=" "p_6%3AAVDBXBAVVSXLQ%2Cp_123%3A110955",
        )
        self.assertEqual(combined_motor.storage_path, "amazon/apple__amazon-mx-apple.json")
        self.assertEqual(
            catalogue_motor.url,
            "https://www.amazon.com.mx/s?rh=p_6%3AAKXVBT49GGF3B",
        )
        self.assertEqual(
            catalogue_motor.storage_path,
            "amazon/ugreen-catalogue__ugreen-group-limited.json",
        )

    def test_amazon_factory_explicit_url_wins_over_filters(self) -> None:
        with empty_article_storage():
            with self.assertLogs("scraper.jobs.factories", level="WARNING") as logs:
                motor = factories._az_factory(
                    "Custom",
                    url="https://example.test/custom",
                    query="ignored",
                    seller=Seller.amazon_mx,
                    brand=AmazonBrand.apple,
                )

        self.assertEqual(motor.url, "https://example.test/custom")
        self.assertEqual(motor.storage_path, "amazon/custom.json")
        self.assertIn("ignoring query/seller/brand", "\n".join(logs.output))

    def test_liverpool_factory_generates_url_without_explicit_url(self) -> None:
        with (
            empty_article_storage(),
            self._mock_liverpool_resolver("N-8BAqotJ%2FHmg946pY%2BECjww%3D%3D?s=ventilador"),
        ):
            motor = factories._lv_factory("Ventilador Liverpool", query="ventilador")

        self.assertEqual(motor.storage_path, "liverpool/ventilador-liverpool.json")
        self.assertEqual(
            motor.url,
            "https://www.liverpool.com.mx/tienda/N-8BAqotJ%2FHmg946pY%2BECjww%3D%3D?s=ventilador",
        )

    def test_liverpool_factory_explicit_url_wins_over_filters(self) -> None:
        with empty_article_storage():
            with self.assertLogs("scraper.jobs.factories", level="WARNING") as logs:
                motor = factories._lv_factory(
                    "Custom",
                    url="https://example.test/custom",
                    query="ignored",
                    page=LiverpoolPage.hornos_electricos,
                    brand="lg",
                )

        self.assertEqual(motor.url, "https://example.test/custom")
        self.assertEqual(motor.storage_path, "liverpool/custom.json")
        self.assertIn("ignoring page/category/query/brand", "\n".join(logs.output))

    def test_liverpool_factory_rejects_generated_brand_filter(self) -> None:
        with empty_article_storage():
            with self.assertRaisesRegex(ValueError, "brand filters require an explicit url"):
                factories._lv_factory("Refrigeradores LG", brand="lg")

    def test_liverpool_factory_generates_seller_filtered_page_query(
        self,
    ) -> None:
        with (
            empty_article_storage(),
            self._mock_liverpool_resolver(
                "N-S1sLjNksKoG%2BC2c1SDPsHDLkL1UcSQDvtOqhAagDbUKyQ4wGi88mGsyxG1aD%2B3uQ",
                LiverpoolPage.hornos_electricos,
            ),
        ):
            motor = factories._lv_factory(
                "Hornos eléctricos Black",
                query="black",
                page=LiverpoolPage.hornos_electricos,
            )

        self.assertEqual(
            motor.url,
            "https://www.liverpool.com.mx/tienda/"
            "N-S1sLjNksKoG%2BC2c1SDPsHDLkL1UcSQDvtOqhAagDbUKyQ4wGi88mGsyxG1aD%2B3uQ?s=black",
        )

    def test_liverpool_factory_generates_landing_page_seller_url(self) -> None:
        with (
            empty_article_storage(),
            self._mock_liverpool_resolver(
                "N-S1sLjNksKoG%2BC2c1SDPsHN%2BJ%2BVnTTvZIur1XfBh58ds%3D",
                LiverpoolPage.computacion,
            ),
        ):
            motor = factories._lv_factory("Computación", page=LiverpoolPage.computacion)

        self.assertEqual(
            motor.url,
            "https://www.liverpool.com.mx/tienda/computaci%C3%B3n/"
            "N-S1sLjNksKoG%2BC2c1SDPsHN%2BJ%2BVnTTvZIur1XfBh58ds%3D",
        )

    def test_palacio_factory_generates_search_url_without_explicit_url(self) -> None:
        with empty_article_storage():
            motor = factories._ph_factory("Magic Keyboard", query="magic keyboard")

        self.assertEqual(motor.storage_path, "palacio_de_hierro/magic-keyboard.json")
        self.assertEqual(
            motor.url,
            "https://www.elpalaciodehierro.com/buscar?q=magic-keyboard",
        )

    def test_palacio_factory_generates_page_url_with_brand_filters(self) -> None:
        with empty_article_storage():
            motor = factories._ph_factory(
                "Computadoras Apple Asus",
                page=PalacioPage.computo,
                brands=["asus", "apple"],
            )

        self.assertEqual(
            motor.url,
            "https://www.elpalaciodehierro.com/electronica/computadoras/apple%7Casus/",
        )

    def test_palacio_factory_explicit_url_wins_over_filters(self) -> None:
        with empty_article_storage():
            with self.assertLogs("scraper.jobs.factories", level="WARNING") as logs:
                motor = factories._ph_factory(
                    "Custom",
                    url="https://example.test/custom",
                    query="ignored",
                    page=PalacioPage.computo,
                    brands=["apple"],
                )

        self.assertEqual(motor.url, "https://example.test/custom")
        self.assertEqual(motor.storage_path, "palacio_de_hierro/custom.json")
        self.assertIn("ignoring page/query/brands", "\n".join(logs.output))

    def test_explicit_url_short_circuits_generated_builders(self) -> None:
        with empty_article_storage():
            with (
                patch(
                    "scraper.jobs.factories.build_mercado_libre_url",
                    side_effect=AssertionError("mercado builder called"),
                ),
                patch(
                    "scraper.jobs.factories.build_amazon_url",
                    side_effect=AssertionError("amazon builder called"),
                ),
                patch(
                    "scraper.jobs.factories.build_liverpool_url",
                    side_effect=AssertionError("liverpool builder called"),
                ),
                patch(
                    "scraper.jobs.factories.build_palacio_url",
                    side_effect=AssertionError("palacio builder called"),
                ),
            ):
                ml_motor = factories._ml_factory(
                    "ML bypass malformed",
                    url="https://example.test/ml",
                    query="ignored",
                    seller=cast(Any, ["bad"]),
                    category=cast(Any, {"bad": "type"}),
                    state=cast(Any, object()),
                )
                az_motor = factories._az_factory(
                    "AZ bypass malformed",
                    url="https://example.test/az",
                    query="ignored",
                    seller=cast(Any, ["bad"]),
                    brand=cast(Any, {"bad": "type"}),
                )
                lv_motor = factories._lv_factory(
                    "LV bypass malformed",
                    url="https://example.test/lv",
                    query="ignored",
                    page=cast(Any, {"bad": "type"}),
                    category=cast(Any, ["bad"]),
                    brand=cast(Any, object()),
                )
                ph_motor = factories._ph_factory(
                    "PH bypass malformed",
                    url="https://example.test/ph",
                    query="ignored",
                    page=cast(Any, {"bad": "type"}),
                    brands=cast(Any, object()),
                )

        self.assertEqual(ml_motor.url, "https://example.test/ml")
        self.assertEqual(az_motor.url, "https://example.test/az")
        self.assertEqual(lv_motor.url, "https://example.test/lv")
        self.assertEqual(ph_motor.url, "https://example.test/ph")


class MotorRegistryTests(unittest.TestCase):
    def test_register_requires_provider_key(self) -> None:
        registry = MotorRegistry()

        with self.assertRaisesRegex(ValueError, "provider"):
            registry.register({"job_id": "missing"})

    def test_build_skips_unknown_provider_and_factory_errors(self) -> None:
        registry = MotorRegistry()
        ok_factory = cast(Any, lambda job_id, url=None, query=None: {"job_id": job_id})
        registry.factory("ok")(ok_factory)

        def failing_factory(
            job_id: str, url: str | None = None, query: str | None = None
        ) -> object:
            raise RuntimeError("boom")

        registry.factory("bad")(failing_factory)  # type: ignore[arg-type]
        registry.register_many(
            [
                {"provider": "missing", "job_id": "skip"},
                {"provider": "bad", "job_id": "skip"},
                {"provider": "ok", "job_id": "keep"},
            ]
        )

        motors = registry.build()

        self.assertEqual(motors, [{"job_id": "keep"}])

    def test_clear_entries_preserves_factories(self) -> None:
        registry = MotorRegistry()
        ok_factory = cast(Any, lambda job_id, url=None, query=None: {"job_id": job_id})
        registry.factory("ok")(ok_factory)
        registry.register({"provider": "ok", "job_id": "one"})
        registry.clear_entries()
        registry.register({"provider": "ok", "job_id": "two"})

        self.assertEqual(registry.providers, ["ok"])
        self.assertEqual(registry.build(), [{"job_id": "two"}])

    def test_factory_registration_requires_job_contract_parameters(self) -> None:
        registry = MotorRegistry()

        with self.assertRaisesRegex(ValueError, "must declare job contract parameters"):
            registry.factory("bad")(lambda job_id: {"job_id": job_id})  # type: ignore[return-value]

        def positional_only(job_id, /, url=None, query=None):  # type: ignore[no-untyped-def]
            return {"job_id": job_id}

        with self.assertRaisesRegex(ValueError, "must not be positional-only"):
            registry.factory("bad2")(positional_only)  # type: ignore[arg-type]

    def test_factory_registration_accepts_job_contract_parameters(self) -> None:
        registry = MotorRegistry()

        def valid_factory(
            job_id: str, url: str | None = None, query: str | None = None, **_
        ) -> dict:
            return {"job_id": job_id}

        registry.factory("ok")(valid_factory)  # type: ignore[arg-type]
        registry.register({"provider": "ok", "job_id": "keep"})
        self.assertEqual(registry.build(), [{"job_id": "keep"}])
