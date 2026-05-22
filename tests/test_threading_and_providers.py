from __future__ import annotations

import asyncio
import ast
import json
import os
import tempfile
import unittest
from collections import Counter
from contextlib import suppress
from pathlib import Path
from typing import Any, cast
from unittest.mock import AsyncMock, patch

import scraper.runtime.orchestrator as orchestrator_module
import scraper.jobs.loader as jobs_loader
from aiohttp import ClientSession, ClientTimeout
from scraper.runtime.config import RuntimeConfig
from shared.articles.article import Article
from shared.scraping.fetchers import AioHttpFetcher
from shared.scraping.motor import Motor
from scraper.runtime.orchestrator import Scrapper
from utils.header_profiles import HEADER_PROFILES
from utils.headers import _base_headers, get_random_header
from utils import telegram
from utils.telegram import _format_price_drop
from provider.amazon.motor import Amazon
from provider.amazon.urls import build_amazon_url
from provider.liverpool.motor import Liverpool
from scraper.jobs.loader import load_jobs
from provider.mercado_libre import parser as mercado_libre_parser
from provider.mercado_libre.motor import MercadoLibre
from provider.mercado_libre.options import Category
from provider.mercado_libre.urls import build_global_search_url
from provider.palacio_de_hierro.motor import PalacioDeHierro
from tests.helpers import empty_article_storage


class Probe:
    def __init__(self) -> None:
        self.active_by_provider: Counter[str] = Counter()
        self.max_by_provider: Counter[str] = Counter()
        self.total_active = 0
        self.max_total_active = 0

    async def enter(self, provider: str) -> None:
        self.active_by_provider[provider] += 1
        self.max_by_provider[provider] = max(
            self.max_by_provider[provider],
            self.active_by_provider[provider],
        )
        self.total_active += 1
        self.max_total_active = max(self.max_total_active, self.total_active)
        await asyncio.sleep(0.02)
        self.total_active -= 1
        self.active_by_provider[provider] -= 1


class DummyMotor:
    def __init__(self, provider_key: str, concurrency_limit: int | None, probe: Probe) -> None:
        self.provider_key = provider_key
        self.CONCURRENCY_LIMIT = concurrency_limit
        self.job_id = f"{provider_key}-job"
        self.blocked_reason = None
        self._probe = probe

    async def scrape(self, caller=None, silent: bool = False) -> None:
        await self._probe.enter(self.provider_key)


class CycleDummyMotor:
    def __init__(self, provider_key: str, delay: float = 0.0, concurrency_limit: int = 1) -> None:
        self.provider_key = provider_key
        self.CONCURRENCY_LIMIT = concurrency_limit
        self.job_id = f"{provider_key}-cycle-job"
        self.blocked_reason = None
        self.delay = delay
        self.started = 0
        self.finished = 0

    async def scrape(self, caller=None, silent: bool = False) -> None:
        self.started += 1
        await asyncio.sleep(self.delay)
        self.finished += 1


class AioHttpDummyMotor:
    FETCH_TIMEOUT_SECONDS = 45
    MAX_RATE_LIMIT_RETRIES = 3
    BLOCKED_BACKOFF_SECONDS = 0
    debug = False

    def _retry_after_delay(self, value):
        return 0

    def mark_blocked(self, reason: str, cooldown: float | int | None = None) -> None:
        self.blocked_reason = reason


class FakeAioHttpResponse:
    status = 200
    headers: dict[str, str] = {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def text(self) -> str:
        return "<html></html>"


class CapturingAioHttpSession:
    def __init__(self) -> None:
        self.timeout: ClientTimeout | None = None

    def get(self, url: str, *, headers: dict[str, str], timeout: ClientTimeout):
        self.timeout = timeout
        return FakeAioHttpResponse()


def make_scrapper(
    motors: list[Any],
    runtime_config: RuntimeConfig | None = None,
) -> Scrapper:
    return Scrapper(
        motors=cast(list[Motor], motors),
        runtime_config=runtime_config or RuntimeConfig(backoff_initial=1, backoff_max=1),
    )


async def wait_until(predicate, timeout: float = 1.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.005)
    raise AssertionError("Timed out waiting for condition.")


async def cancel_task(task: asyncio.Task) -> None:
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task


class PackageBoundaryTests(unittest.TestCase):
    PRODUCTION_ROOTS = (
        Path("app.py"),
        Path("shared"),
        Path("scraper"),
        Path("provider"),
        Path("utils"),
    )

    def test_root_contains_only_app_entrypoint(self) -> None:
        root_files = sorted(path.name for path in Path(".").glob("*.py"))

        self.assertEqual(root_files, ["app.py"])

    def test_provider_root_contains_only_package_initializer(self) -> None:
        root_files = sorted(path.name for path in Path("provider").glob("*.py"))

        self.assertEqual(root_files, ["__init__.py"])

    def test_scraper_root_contains_only_package_initializer(self) -> None:
        root_files = sorted(path.name for path in Path("scraper").glob("*.py"))

        self.assertEqual(root_files, ["__init__.py"])

    def test_shared_does_not_import_provider_or_scraper(self) -> None:
        offenders = self._imports_from_package(Path("shared"), {"provider", "scraper"})

        self.assertEqual(offenders, [])

    def test_provider_does_not_import_scraper(self) -> None:
        offenders = self._imports_from_package(Path("provider"), {"scraper"})

        self.assertEqual(offenders, [])

    def test_removed_legacy_import_paths_are_absent(self) -> None:
        legacy_paths = {
            "provider.loader",
            "provider.factories",
            "provider.registry",
            "provider.generator",
            "scraper.article",
            "scraper.article_lifecycle",
            "scraper.article_repository",
            "scraper.fetchers",
            "scraper.motor",
            "scraper.motor_config",
            "scraper.status",
            "scraper.stream",
        }
        offenders = self._imports_matching(Path("."), legacy_paths)

        self.assertEqual(offenders, [])

    def test_removed_root_scrapper_module_is_not_imported(self) -> None:
        offenders = self._imports_from_package(Path("."), {"scrapper"})

        self.assertEqual(offenders, [])

    @staticmethod
    def _python_files(root: Path) -> list[Path]:
        if root == Path("."):
            files: list[Path] = []
            for production_root in PackageBoundaryTests.PRODUCTION_ROOTS:
                if production_root.is_file():
                    files.append(production_root)
                elif production_root.is_dir():
                    files.extend(PackageBoundaryTests._python_files(production_root))
            return sorted(files)

        return sorted(
            path
            for path in root.rglob("*.py")
            if "__pycache__" not in path.parts and "data" not in path.parts
        )

    def _imports_from_package(self, root: Path, forbidden: set[str]) -> list[str]:
        offenders: list[str] = []
        for path in self._python_files(root):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [node.module or ""]
                else:
                    continue
                for name in names:
                    package = name.split(".", 1)[0]
                    if package in forbidden:
                        offenders.append(f"{path}:{name}")
        return offenders

    def _imports_matching(self, root: Path, forbidden_modules: set[str]) -> list[str]:
        offenders: list[str] = []
        for path in self._python_files(root):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [node.module or ""]
                else:
                    continue

                for name in names:
                    if any(
                        name == forbidden or name.startswith(f"{forbidden}.")
                        for forbidden in forbidden_modules
                    ):
                        offenders.append(f"{path}:{name}")
        return offenders


class ProviderConcurrencyTests(unittest.IsolatedAsyncioTestCase):
    async def test_same_provider_jobs_are_serialized_when_limit_is_one(self) -> None:
        probe = Probe()
        motors = [DummyMotor("ml", 1, probe) for _ in range(3)]
        scrapper = make_scrapper(motors)

        await asyncio.gather(*(scrapper._scrape_with_limit(cast(Motor, motor)) for motor in motors))

        self.assertEqual(probe.max_by_provider["ml"], 1)
        self.assertEqual(scrapper.health["providers"]["ml"]["configured_limit"], 1)

    async def test_two_job_providers_can_run_two_jobs_at_once(self) -> None:
        probe = Probe()
        motors = [DummyMotor("lv", 2, probe) for _ in range(3)]
        scrapper = make_scrapper(motors)

        await asyncio.gather(*(scrapper._scrape_with_limit(cast(Motor, motor)) for motor in motors))

        self.assertEqual(probe.max_by_provider["lv"], 2)
        self.assertEqual(scrapper.health["providers"]["lv"]["configured_limit"], 2)

    async def test_different_providers_run_in_parallel(self) -> None:
        probe = Probe()
        motors = [
            DummyMotor("ml", 1, probe),
            DummyMotor("az", 1, probe),
        ]
        scrapper = make_scrapper(motors)

        await asyncio.gather(*(scrapper._scrape_with_limit(cast(Motor, motor)) for motor in motors))

        self.assertEqual(probe.max_by_provider["ml"], 1)
        self.assertEqual(probe.max_by_provider["az"], 1)
        self.assertEqual(probe.max_total_active, 2)

    def test_invalid_provider_limit_clamps_to_one(self) -> None:
        probe = Probe()
        scrapper = make_scrapper([DummyMotor("bad", 0, probe)])

        scrapper._get_provider_semaphore("bad", 0)

        self.assertEqual(scrapper.health["providers"]["bad"]["configured_limit"], 1)

    def test_missing_provider_limit_uses_internal_fallback(self) -> None:
        probe = Probe()
        scrapper = make_scrapper([DummyMotor("fallback", None, probe)])

        self.assertEqual(scrapper.health["providers"]["fallback"]["configured_limit"], 1)

    def test_legacy_max_concurrent_motors_fallback_was_removed(self) -> None:
        source = Path(orchestrator_module.__file__).read_text(encoding="utf-8")

        self.assertNotIn("MAX_CONCURRENT_MOTORS", source)
        self.assertEqual(orchestrator_module.DEFAULT_PROVIDER_CONCURRENCY, 1)


class ProviderCycleSchedulerTests(unittest.IsolatedAsyncioTestCase):
    async def test_fast_provider_starts_next_cycle_without_waiting_for_slow_provider(self) -> None:
        fast = CycleDummyMotor("fast", delay=0.005)
        slow = CycleDummyMotor("slow", delay=0.2)
        scrapper = make_scrapper([fast, slow])
        scrapper.sleep_time = 0.005

        task = asyncio.create_task(scrapper.run())
        try:
            await wait_until(
                lambda: (
                    scrapper.health["providers"]["fast"]["cycle_count"] >= 2 and slow.started == 1
                )
            )

            self.assertGreaterEqual(scrapper.health["providers"]["fast"]["cycle_count"], 2)
            self.assertEqual(scrapper.health["providers"]["slow"]["cycle_count"], 0)
            self.assertEqual(scrapper.health["providers"]["slow"]["status"], "running")
            self.assertEqual(slow.finished, 0)
        finally:
            await cancel_task(task)

    async def test_provider_health_updates_independently_after_cycle_finishes(self) -> None:
        fast = CycleDummyMotor("fast", delay=0.005)
        slow = CycleDummyMotor("slow", delay=0.2)
        scrapper = make_scrapper([fast, slow])
        scrapper.sleep_time = 0.005

        task = asyncio.create_task(scrapper.run())
        try:
            await wait_until(
                lambda: (
                    scrapper.health["providers"]["fast"]["cycle_count"] >= 1
                    and scrapper.health["providers"]["slow"]["status"] == "running"
                )
            )

            fast_health = scrapper.health["providers"]["fast"]
            slow_health = scrapper.health["providers"]["slow"]
            self.assertEqual(fast_health["status"], "ok")
            self.assertIsNotNone(fast_health["last_cycle_started_at"])
            self.assertIsNotNone(fast_health["last_cycle_finished_at"])
            self.assertIsNotNone(fast_health["last_cycle_duration_s"])
            self.assertEqual(fast_health["last_error"], None)
            self.assertEqual(slow_health["status"], "running")
            self.assertEqual(slow_health["cycle_count"], 0)
            self.assertEqual(
                scrapper.health["last_cycle_finished_at"], fast_health["last_cycle_finished_at"]
            )
        finally:
            await cancel_task(task)

    async def test_provider_loop_failure_does_not_stop_other_providers(self) -> None:
        failing = CycleDummyMotor("failing", delay=0.0)
        healthy = CycleDummyMotor("healthy", delay=0.005)
        scrapper = make_scrapper(
            [failing, healthy],
            RuntimeConfig(backoff_initial=0.05, backoff_max=0.05),
        )
        scrapper.sleep_time = 0.005
        original_scrape_with_limit = scrapper._scrape_with_limit

        async def scrape_with_scheduler_failure(motor) -> None:
            if motor.provider_key == "failing":
                raise RuntimeError("scheduler boom")
            await original_scrape_with_limit(motor)

        scrapper._scrape_with_limit = scrape_with_scheduler_failure

        task = asyncio.create_task(scrapper.run())
        try:
            await wait_until(
                lambda: (
                    scrapper.health["providers"]["failing"]["status"] == "error"
                    and scrapper.health["providers"]["healthy"]["cycle_count"] >= 1
                )
            )

            failing_health = scrapper.health["providers"]["failing"]
            healthy_health = scrapper.health["providers"]["healthy"]
            self.assertEqual(failing_health["last_error"], "scheduler boom")
            self.assertEqual(failing_health["cycle_count"], 0)
            self.assertEqual(healthy_health["status"], "ok")
            self.assertGreaterEqual(healthy_health["cycle_count"], 1)
        finally:
            await cancel_task(task)


class TelegramFormatterTests(unittest.TestCase):
    def test_price_drop_message_uses_previous_and_new_price(self) -> None:
        message = _format_price_drop(
            {
                "job_id": "Nintendo",
                "title": "Nintendo 3DS",
                "url": "https://example.test/item",
                "previous_price": 2000.0,
                "new_price": 1500.0,
                "percent_change": "25.00",
                "history": [{"datetime": "2026-01-01"}],
            }
        )

        self.assertIsNotNone(message)
        assert message is not None
        self.assertIn("$2,000.00", message)
        self.assertIn("$1,500.00 MXN", message)
        self.assertIn("Save $500.00", message)
        self.assertIn("25.0% OFF", message)


class ConfigPathResolutionTests(unittest.TestCase):
    def test_default_jobs_path_is_repo_root_based(self) -> None:
        expected_jobs = load_jobs(jobs_loader.DEFAULT_CONFIG_PATH)
        original_cwd = Path.cwd()
        with tempfile.TemporaryDirectory() as tmpdir:
            try:
                os.chdir(tmpdir)
                jobs = load_jobs()
            finally:
                os.chdir(original_cwd)

        self.assertTrue(jobs_loader.DEFAULT_CONFIG_PATH.is_absolute())
        self.assertEqual(jobs, expected_jobs)

    def test_telegram_config_path_is_repo_root_based(self) -> None:
        original_cwd = Path.cwd()
        with tempfile.TemporaryDirectory() as tmpdir:
            try:
                os.chdir(tmpdir)
                token, chat_id = telegram._load_config()
            finally:
                os.chdir(original_cwd)

        self.assertTrue(telegram._CONFIG_PATH.is_absolute())
        self.assertEqual((token, chat_id), ("", ""))


class FetchStrategyConfigTests(unittest.TestCase):
    def test_default_fetch_strategy_is_aiohttp(self) -> None:
        with empty_article_storage():
            motor = Amazon(
                "macbook", build_amazon_url(query="macbook"), storage_path="tests/amazon.json"
            )

        self.assertEqual(motor.FETCH_STRATEGY, "aiohttp")

    def test_mercado_libre_fetch_strategy_is_browser(self) -> None:
        with empty_article_storage():
            motor = MercadoLibre(
                "pokemon ds",
                build_global_search_url("pokemon ds", category=Category.consolas),
                storage_path="tests/ml.json",
            )

        self.assertEqual(motor.FETCH_STRATEGY, "browser")
        self.assertEqual(motor.BROWSER_WAIT_SELECTOR, "section.ui-search-results")

    def test_invalid_fetch_strategy_raises_clear_error(self) -> None:
        with self.assertRaisesRegex(ValueError, "FETCH_STRATEGY"):
            Motor._coerce_fetch_strategy("spaceship")


class FetchDelegationTests(unittest.IsolatedAsyncioTestCase):
    async def test_aiohttp_fetch_uses_configured_timeout(self) -> None:
        motor = AioHttpDummyMotor()
        session = CapturingAioHttpSession()

        html = await AioHttpFetcher().fetch(
            motor, cast(ClientSession, session), "https://example.test"
        )

        self.assertEqual(html, "<html></html>")
        self.assertIsNotNone(session.timeout)
        assert session.timeout is not None
        self.assertEqual(session.timeout.connect, 10)
        self.assertEqual(session.timeout.sock_read, 45)

    async def test_motor_delegates_to_configured_fetcher(self) -> None:
        with empty_article_storage():
            motor = Amazon(
                "macbook", build_amazon_url(query="macbook"), storage_path="tests/amazon.json"
            )
        fake_fetcher = AsyncMock()
        fake_fetcher.fetch.return_value = "<html></html>"

        with patch("shared.scraping.motor.get_fetcher", return_value=fake_fetcher) as get_fetcher:
            html = await motor._fetch(
                session=cast(ClientSession, None),
                url="https://example.test",
            )

        self.assertEqual(html, "<html></html>")
        get_fetcher.assert_called_once_with("aiohttp")
        fake_fetcher.fetch.assert_awaited_once()

    async def test_provider_can_opt_into_browser_strategy_by_config_value(self) -> None:
        with empty_article_storage():
            motor = Amazon(
                "macbook", build_amazon_url(query="macbook"), storage_path="tests/amazon.json"
            )
        motor.FETCH_STRATEGY = "browser"
        fake_fetcher = AsyncMock()
        fake_fetcher.fetch.return_value = "<html></html>"

        with patch("shared.scraping.motor.get_fetcher", return_value=fake_fetcher) as get_fetcher:
            await motor._fetch(
                session=cast(ClientSession, None),
                url="https://example.test",
            )

        get_fetcher.assert_called_once_with("browser")


class MercadoLibreStabilityTests(unittest.IsolatedAsyncioTestCase):
    async def test_js_gate_marks_scrape_incomplete_and_keeps_active_items(self) -> None:
        html = """
        <html>
          <head><title>Pokemon Ds | MercadoLibre</title></head>
          <body>This page requires JavaScript to work. Please enable JavaScript in your browser to continue.</body>
        </html>
        """
        with empty_article_storage():
            motor = MercadoLibre(
                "pokemon ds",
                build_global_search_url("pokemon ds", category=Category.consolas),
                storage_path="tests/ml-js-gate.json",
            )
        existing = Article(
            identifier="MLM123", title="Pokemon", price=100.0, url="https://example.test/item"
        )
        motor.active.add(existing)

        async def fake_fetch(session, url, retries=3):
            return html

        motor._fetch = fake_fetch
        motor.save_to_file = AsyncMock()

        await motor.scrape(silent=True)

        self.assertTrue(motor._scrape_incomplete)
        self.assertEqual(motor.blocked_reason, "mercado_libre_js_required")
        self.assertIn(existing, motor.active)
        self.assertEqual(len(motor.on_hold), 0)
        motor.save_to_file.assert_awaited_once()

    async def test_browser_fetch_timeout_does_not_reconcile_missing_items(self) -> None:
        with empty_article_storage():
            motor = MercadoLibre(
                "pokemon ds",
                build_global_search_url("pokemon ds", category=Category.consolas),
                storage_path="tests/ml-timeout.json",
            )
        existing = Article(
            identifier="MLM123", title="Pokemon", price=100.0, url="https://example.test/item"
        )
        motor.active.add(existing)

        async def fake_fetch(session, url, retries=3):
            motor.mark_blocked("browser_timeout", 0)
            return None

        motor._fetch = fake_fetch
        motor.save_to_file = AsyncMock()

        await motor.scrape(silent=True)

        self.assertTrue(motor._scrape_incomplete)
        self.assertEqual(motor.blocked_reason, "browser_timeout")
        self.assertIn(existing, motor.active)
        self.assertEqual(len(motor.on_hold), 0)


class ProviderParserFixtureTests(unittest.TestCase):
    def test_amazon_parser_handles_search_result_fixture(self) -> None:
        html = """
        <div data-component-type="s-search-result" data-asin="B012345678">
          <h2><span>Apple MacBook Test</span></h2>
          <span class="a-price"><span class="a-offscreen">$12,999.50</span></span>
        </div>
        <a class="s-pagination-next" href="/s?k=macbook&page=2">Next</a>
        """
        with empty_article_storage():
            motor = Amazon(
                "macbook", build_amazon_url(query="macbook"), storage_path="tests/amazon.json"
            )

        items, next_url = motor.scrape_page({"content": html, "url": motor.url})

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["identifier"], "B012345678")
        self.assertEqual(items[0]["price"], 12999.50)
        self.assertEqual(next_url, "https://www.amazon.com.mx/s?k=macbook&page=2")

    def test_liverpool_parser_handles_next_data_fixture(self) -> None:
        page_object = {
            "query": {
                "data": {
                    "mainContent": {
                        "records": [
                            {
                                "allMeta": {
                                    "id": "1190039346",
                                    "title": "Laptop Lenovo Test",
                                    "minimumPromoPrice": 21419.1,
                                }
                            }
                        ],
                        "pageInfo": {"noOfPages": "2"},
                    }
                }
            }
        }
        html = (
            f"<script id='__NEXT_DATA__' type='application/json'>{json.dumps(page_object)}</script>"
        )
        with empty_article_storage():
            motor = Liverpool(
                "Laptops",
                "https://www.liverpool.com.mx/tienda/Laptops/example",
                storage_path="tests/lv.json",
            )

        items, next_url = motor.scrape_page({"content": html, "url": motor.url})

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["identifier"], "1190039346")
        self.assertEqual(items[0]["price"], 21419.1)
        self.assertEqual(next_url, f"{motor.url}/page-2")

    def test_palacio_parser_handles_constructor_fixture(self) -> None:
        html = """
        <section data-component="search/ConstructorSearch" data-component-options='{"pageSize": 52}'></section>
        <div data-cnstrc-num-results="1"></div>
        <div data-cnstrc-item-section="Products" data-pid="45329637"
             data-cnstrc-item-name="MacBook Air Test" data-cnstrc-item-price="24999">
          <a href="/apple-macbook-air-test-45329637.html">MacBook Air Test</a>
        </div>
        """
        with empty_article_storage():
            motor = PalacioDeHierro(
                "Macbook",
                "https://www.elpalaciodehierro.com/buscar?q=macbook",
                storage_path="tests/ph.json",
            )

        items, next_url = motor.scrape_page({"content": html, "url": motor.url})

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["identifier"], "45329637")
        self.assertEqual(items[0]["price"], 24999.0)
        self.assertEqual(
            items[0]["url"],
            "https://www.elpalaciodehierro.com/apple-macbook-air-test-45329637.html",
        )
        self.assertIsNone(next_url)

    def test_mercado_libre_parser_reports_blocked_js_gate(self) -> None:
        html = """
        <html>
          <body>This page requires JavaScript. Please enable JavaScript.</body>
        </html>
        """

        result = mercado_libre_parser.parse_search_page(
            html,
            "https://listado.mercadolibre.com.mx/consolas-videojuegos/test_NoIndex_True",
        )

        self.assertEqual(result.items, [])
        self.assertIsNone(result.next_url)
        self.assertEqual(result.blocked_reason, "mercado_libre_js_required")

    def test_mercado_libre_parser_handles_saved_root_source_fixture(self) -> None:
        fixture = Path("tests/fixtures/mercado_libre/search_results.html")
        html = fixture.read_text(encoding="utf-8", errors="replace")
        url = "https://listado.mercadolibre.com.mx/consolas-videojuegos/test_NoIndex_True"
        with empty_article_storage():
            motor = MercadoLibre("nintendo", url, storage_path="tests/ml-source.json")

        items, next_url = motor.scrape_page({"content": html, "url": url})

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["identifier"], "MLM123")
        self.assertEqual(items[0]["title"], "Nintendo Fixture")
        self.assertEqual(items[0]["price"], 6000.0)
        self.assertEqual(next_url, url.replace("_NoIndex_True", "_Desde_2_NoIndex_True"))

    def test_mercado_libre_nordic_state_fallback_without_dom_cards(self) -> None:
        state = {
            "appProps": {
                "pageProps": {
                    "initialState": {
                        "results": [
                            {
                                "polycard": {
                                    "metadata": {
                                        "id": "MLM123",
                                        "user_product_id": "MLMU123",
                                        "url": "www.mercadolibre.com.mx/test/up/MLMU123",
                                        "url_fragments": "#tracking=1",
                                    },
                                    "components": [
                                        {"type": "title", "title": {"text": "Nintendo Test"}},
                                        {
                                            "type": "price",
                                            "price": {"current_price": {"value": 1234.5}},
                                        },
                                    ],
                                }
                            }
                        ],
                        "pagination": {
                            "next_page": {
                                "show": True,
                                "url": "https://listado.mercadolibre.com.mx/test_Desde_49_NoIndex_True",
                            }
                        },
                    }
                }
            }
        }
        html = f"<script id='__NORDIC_RENDERING_CTX__'>_n.ctx.r={json.dumps(state)}</script>"
        with empty_article_storage():
            motor = MercadoLibre(
                "nintendo",
                build_global_search_url("nintendo", category=Category.consolas),
                storage_path="tests/ml-nordic.json",
            )

        items, next_url = motor.scrape_page({"content": html, "url": motor.url})

        self.assertEqual(
            items,
            [
                {
                    "identifier": "MLMU123",
                    "title": "Nintendo Test",
                    "price": 1234.5,
                    "url": "https://www.mercadolibre.com.mx/test/up/MLMU123",
                }
            ],
        )
        self.assertEqual(next_url, "https://listado.mercadolibre.com.mx/test_Desde_49_NoIndex_True")


class HeaderGenerationTests(unittest.TestCase):
    def test_base_headers_render_required_browser_fields(self) -> None:
        headers = _base_headers(HEADER_PROFILES[0])

        self.assertIn("User-Agent", headers)
        self.assertIn("Accept-Language", headers)
        self.assertIn("Accept-Encoding", headers)
        self.assertIn("Sec-Fetch-Site", headers)

    def test_get_random_header_preserves_public_api(self) -> None:
        headers = get_random_header()

        self.assertIsInstance(headers, dict)
        self.assertIn("User-Agent", headers)
        self.assertIn("Accept", headers)


if __name__ == "__main__":
    unittest.main()
