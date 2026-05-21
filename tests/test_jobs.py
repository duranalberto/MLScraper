from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from provider.amazon.options import Seller
from provider.liverpool import urls as lv_urls
from provider.liverpool.options import (
    LIVERPOOL_SELLER_REFINEMENT_NAME,
    LIVERPOOL_SELLER_REFINEMENT_VALUE,
)
from provider.liverpool.options import Page as LiverpoolPage
from provider.mercado_libre.options import Category
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
    search_term: " pokemon ds "
    category: consolas
    custom: passthrough
  - provider: az
    search_term: macbook
    seller: amazon_mx
""")

        jobs = load_jobs(path)

        self.assertEqual(jobs[0]["search_term"], "pokemon ds")
        self.assertEqual(jobs[0]["category"], Category.consolas)
        self.assertEqual(jobs[0]["custom"], "passthrough")
        self.assertEqual(jobs[1]["seller"], Seller.amazon_mx)

    def test_load_jobs_coerces_liverpool_page_and_ignores_seller(self) -> None:
        path = self._write_jobs("""
jobs:
  - provider: lv
    search_term: Hornos eléctricos Black
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
    search_term: Juegos Nintendo
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
    search_term: valid
    category: unknown
  - provider: ph
    search_term: missing url
  - provider: lv
    search_term: ok
    url: https://example.test/list
""")

        jobs = load_jobs(path)

        self.assertEqual(
            jobs, [{"provider": "lv", "search_term": "ok", "url": "https://example.test/list"}]
        )

    def test_load_jobs_skips_unknown_liverpool_page_names(self) -> None:
        path = self._write_jobs("""
jobs:
  - provider: lv
    search_term: bad
    page: missing
  - provider: lv
    search_term: good
    page: Apple
""")

        jobs = load_jobs(path)

        self.assertEqual(
            jobs, [{"provider": "lv", "search_term": "good", "page": LiverpoolPage.apple}]
        )

    def test_load_jobs_skips_conflicting_liverpool_page_and_category(self) -> None:
        path = self._write_jobs("""
jobs:
  - provider: lv
    search_term: conflict
    page: laptops
    category: tablets
""")

        jobs = load_jobs(path)

        self.assertEqual(jobs, [])

    def test_load_jobs_handles_empty_jobs_list_and_rejects_bad_structure(self) -> None:
        empty_path = self._write_jobs("jobs:\n")
        missing_jobs_path = self._write_jobs("providers: []\n")
        non_list_path = self._write_jobs("jobs: {}\n")

        self.assertEqual(load_jobs(empty_path), [])
        with self.assertRaisesRegex(ValueError, "top-level 'jobs'"):
            load_jobs(missing_jobs_path)
        with self.assertRaisesRegex(ValueError, "must be a list"):
            load_jobs(non_list_path)


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
                {"provider": "ml", "search_term": "Nintendo DS", "category": Category.videojuegos},
                {"provider": "az", "search_term": "iPhone", "seller": Seller.amazon_mx},
                {"provider": "lv", "search_term": "LV Laptops", "url": "https://example.test/lv"},
                {"provider": "ph", "search_term": "PH Apple", "url": "https://example.test/ph"},
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

    def test_liverpool_factory_generates_url_without_explicit_url(self) -> None:
        with empty_article_storage(), self._mock_liverpool_resolver(
            "N-8BAqotJ%2FHmg946pY%2BECjww%3D%3D?s=ventilador"
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
        self.assertIn("ignoring page/category/query/brand", "\n".join(logs.output))

    def test_liverpool_factory_rejects_generated_brand_filter(self) -> None:
        with empty_article_storage():
            with self.assertRaisesRegex(ValueError, "brand filters require an explicit url"):
                factories._lv_factory("Refrigeradores LG", brand="lg")

    def test_liverpool_factory_generates_seller_filtered_page_query(
        self,
    ) -> None:
        with empty_article_storage(), self._mock_liverpool_resolver(
            "N-S1sLjNksKoG%2BC2c1SDPsHDLkL1UcSQDvtOqhAagDbUKyQ4wGi88mGsyxG1aD%2B3uQ",
            LiverpoolPage.hornos_electricos,
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
        with empty_article_storage(), self._mock_liverpool_resolver(
            "N-S1sLjNksKoG%2BC2c1SDPsHN%2BJ%2BVnTTvZIur1XfBh58ds%3D",
            LiverpoolPage.computacion,
        ):
            motor = factories._lv_factory("Computación", page=LiverpoolPage.computacion)

        self.assertEqual(
            motor.url,
            "https://www.liverpool.com.mx/tienda/computaci%C3%B3n/"
            "N-S1sLjNksKoG%2BC2c1SDPsHN%2BJ%2BVnTTvZIur1XfBh58ds%3D",
        )


class MotorRegistryTests(unittest.TestCase):
    def test_register_requires_provider_key(self) -> None:
        registry = MotorRegistry()

        with self.assertRaisesRegex(ValueError, "provider"):
            registry.register({"search_term": "missing"})

    def test_build_skips_unknown_provider_and_factory_errors(self) -> None:
        registry = MotorRegistry()
        registry.factory("ok")(lambda search_term: {"search_term": search_term})  # type: ignore[return-value]

        def failing_factory(search_term: str) -> object:
            raise RuntimeError("boom")

        registry.factory("bad")(failing_factory)  # type: ignore[arg-type]
        registry.register_many(
            [
                {"provider": "missing", "search_term": "skip"},
                {"provider": "bad", "search_term": "skip"},
                {"provider": "ok", "search_term": "keep"},
            ]
        )

        motors = registry.build()

        self.assertEqual(motors, [{"search_term": "keep"}])

    def test_clear_entries_preserves_factories(self) -> None:
        registry = MotorRegistry()
        registry.factory("ok")(lambda search_term: {"search_term": search_term})  # type: ignore[return-value]
        registry.register({"provider": "ok", "search_term": "one"})
        registry.clear_entries()
        registry.register({"provider": "ok", "search_term": "two"})

        self.assertEqual(registry.providers, ["ok"])
        self.assertEqual(registry.build(), [{"search_term": "two"}])
