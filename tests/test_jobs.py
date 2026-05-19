from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from provider.amazon.options import Seller
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
