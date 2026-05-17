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
from unittest.mock import AsyncMock, Mock, patch

import scraper.runtime.orchestrator as orchestrator_module
from aiohttp import ClientTimeout
from scraper.runtime.config import RuntimeConfig
from scraper.runtime.notifications import broadcast_is_updated, broadcast_new_element
from shared.articles.article import Article
from shared.articles.lifecycle import ArticleLifecycle
from shared.articles.status import Status
from shared.articles.stream import Stream
from shared.scraping.fetchers import AioHttpFetcher, BrowserFetcher
from shared.scraping.motor import Motor
from scraper.runtime.orchestrator import Scrapper
from utils.header_profiles import HEADER_PROFILES
from utils.headers import _base_headers, get_random_header
from utils import telegram
from utils.telegram import _format_price_drop
from provider.amazon.motor import Amazon
from provider.amazon.options import Seller
from provider.liverpool.motor import Liverpool
from scraper.jobs.loader import load_jobs
from provider.mercado_libre import parser as mercado_libre_parser
from provider.mercado_libre.motor import MercadoLibre
from provider.mercado_libre.options import Category
from provider.palacio_de_hierro.motor import PalacioDeHierro


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
    def __init__(self, provider_key: str, concurrency_limit: int, probe: Probe) -> None:
        self.provider_key = provider_key
        self.CONCURRENCY_LIMIT = concurrency_limit
        self.search_term = f"{provider_key}-job"
        self.blocked_reason = None
        self._probe = probe

    async def scrape(self, caller=None, silent: bool = False) -> None:
        await self._probe.enter(self.provider_key)


class CycleDummyMotor:
    def __init__(self, provider_key: str, delay: float = 0.0, concurrency_limit: int = 1) -> None:
        self.provider_key = provider_key
        self.CONCURRENCY_LIMIT = concurrency_limit
        self.search_term = f"{provider_key}-cycle-job"
        self.blocked_reason = None
        self.delay = delay
        self.started = 0
        self.finished = 0

    async def scrape(self, caller=None, silent: bool = False) -> None:
        self.started += 1
        await asyncio.sleep(self.delay)
        self.finished += 1


class FetchDummyMotor:
    def __init__(
        self,
        *,
        wait_selector: str | None = "section.results",
        block_selectors: tuple[str, ...] = (),
        timeout: int = 1,
    ) -> None:
        self.FETCH_TIMEOUT_SECONDS = timeout
        self.BROWSER_WAIT_SELECTOR = wait_selector
        self.BROWSER_BLOCK_SELECTORS = block_selectors
        self.BLOCKED_BACKOFF_SECONDS = 0
        self.blocked_reason = None
        self.debug = False

    def mark_blocked(self, reason: str, cooldown: float | int | None = None) -> None:
        self.blocked_reason = reason


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


class FakeLocator:
    def __init__(self, count: int) -> None:
        self._count = count

    async def count(self) -> int:
        return self._count


class FakePage:
    def __init__(
        self,
        selectors: dict[str, int],
        content: str = "<html></html>",
        url: str = "https://example.test",
    ) -> None:
        self.selectors = selectors
        self._content = content
        self.url = url
        self.closed = False

    async def goto(self, url: str, wait_until: str, timeout: int) -> None:
        self.url = self.url if self.url != "https://example.test" else url

    def locator(self, selector: str) -> FakeLocator:
        return FakeLocator(self.selectors.get(selector, 0))

    async def content(self) -> str:
        return self._content

    async def close(self) -> None:
        self.closed = True


class FakeContext:
    def __init__(self, page: FakePage) -> None:
        self.page = page

    async def new_page(self) -> FakePage:
        return self.page


def make_scrapper(
    motors: list[DummyMotor],
    runtime_config: RuntimeConfig | None = None,
) -> Scrapper:
    return Scrapper(
        motors=motors,
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
        legacy_paths = [
            ".".join(parts)
            for parts in [
                ("provider", "loader"),
                ("provider", "factories"),
                ("provider", "registry"),
                ("provider", "generator"),
                ("scraper", "article"),
                ("scraper", "article_lifecycle"),
                ("scraper", "article_repository"),
                ("scraper", "fetchers"),
                ("scraper", "motor"),
                ("scraper", "motor_config"),
                ("scraper", "status"),
                ("scraper", "stream"),
            ]
        ]
        offenders: list[str] = []
        for path in self._python_files(Path(".")):
            source = path.read_text(encoding="utf-8")
            for legacy_path in legacy_paths:
                if legacy_path in source:
                    offenders.append(f"{path}:{legacy_path}")

        self.assertEqual(offenders, [])

    def test_removed_root_scrapper_module_is_not_imported(self) -> None:
        offenders = self._imports_from_package(Path("."), {"scrapper"})

        self.assertEqual(offenders, [])

    @staticmethod
    def _python_files(root: Path) -> list[Path]:
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


class ProviderConcurrencyTests(unittest.IsolatedAsyncioTestCase):
    async def test_same_provider_jobs_are_serialized_when_limit_is_one(self) -> None:
        probe = Probe()
        motors = [DummyMotor("ml", 1, probe) for _ in range(3)]
        scrapper = make_scrapper(motors)

        await asyncio.gather(*(scrapper._scrape_with_limit(motor) for motor in motors))

        self.assertEqual(probe.max_by_provider["ml"], 1)
        self.assertEqual(scrapper.health["providers"]["ml"]["configured_limit"], 1)

    async def test_two_job_providers_can_run_two_jobs_at_once(self) -> None:
        probe = Probe()
        motors = [DummyMotor("lv", 2, probe) for _ in range(3)]
        scrapper = make_scrapper(motors)

        await asyncio.gather(*(scrapper._scrape_with_limit(motor) for motor in motors))

        self.assertEqual(probe.max_by_provider["lv"], 2)
        self.assertEqual(scrapper.health["providers"]["lv"]["configured_limit"], 2)

    async def test_different_providers_run_in_parallel(self) -> None:
        probe = Probe()
        motors = [
            DummyMotor("ml", 1, probe),
            DummyMotor("az", 1, probe),
        ]
        scrapper = make_scrapper(motors)

        await asyncio.gather(*(scrapper._scrape_with_limit(motor) for motor in motors))

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


class BroadcastNotificationTests(unittest.IsolatedAsyncioTestCase):
    async def test_new_item_logs_when_not_initial_scrape(self) -> None:
        element = {
            "search_term": "Nintendo",
            "title": "Nintendo 3DS",
            "price": 2500.0,
            "url": "https://example.test/item",
            "is_initial_scrape": False,
        }
        send_new = AsyncMock()
        logger = Mock()

        await broadcast_new_element(element, send_new=send_new, logger=logger)

        logger.info.assert_called_once_with(
            "NEW ITEM: %s | %s | $%s | %s",
            "Nintendo",
            "Nintendo 3DS",
            2500.0,
            "https://example.test/item",
        )
        send_new.assert_awaited_once_with(element)

    async def test_new_item_log_is_suppressed_on_initial_scrape(self) -> None:
        element = {
            "search_term": "Nintendo",
            "title": "Nintendo 3DS",
            "price": 2500.0,
            "url": "https://example.test/item",
            "is_initial_scrape": True,
        }
        send_new = AsyncMock()
        logger = Mock()

        await broadcast_new_element(element, send_new=send_new, logger=logger)

        logger.info.assert_not_called()
        send_new.assert_awaited_once_with(element)

    async def test_price_drop_broadcast_includes_previous_and_new_price(self) -> None:
        element = {
            "search_term": "Nintendo",
            "title": "Nintendo 3DS",
            "price": 1500.0,
            "url": "https://example.test/item",
            "history": [{"price": 2000.0, "datetime": "2026-01-01"}],
        }
        send_drop = AsyncMock()
        logger = Mock()

        await broadcast_is_updated(element, send_price_drop=send_drop, logger=logger)

        self.assertEqual(element["previous_price"], 2000.0)
        self.assertEqual(element["new_price"], 1500.0)
        self.assertEqual(element["percent_change"], "25.00")
        logger.info.assert_called_once_with(
            "PRICE DROP: %s | $%.2f -> $%.2f (%s%%) — %s",
            "Nintendo 3DS",
            2000.0,
            1500.0,
            "25.00",
            "https://example.test/item",
        )
        send_drop.assert_awaited_once_with(element)


class TelegramFormatterTests(unittest.TestCase):
    def test_price_drop_message_uses_previous_and_new_price(self) -> None:
        message = _format_price_drop(
            {
                "search_term": "Nintendo",
                "title": "Nintendo 3DS",
                "url": "https://example.test/item",
                "previous_price": 2000.0,
                "new_price": 1500.0,
                "percent_change": "25.00",
                "history": [{"datetime": "2026-01-01"}],
            }
        )

        self.assertIsNotNone(message)
        self.assertIn("$2,000.00", message)
        self.assertIn("$1,500.00 MXN", message)
        self.assertIn("Save $500.00", message)
        self.assertIn("25.0% OFF", message)


class ConfigPathResolutionTests(unittest.TestCase):
    def test_default_jobs_path_is_repo_root_based(self) -> None:
        original_cwd = Path.cwd()
        with tempfile.TemporaryDirectory() as tmpdir:
            try:
                os.chdir(tmpdir)
                jobs = load_jobs()
            finally:
                os.chdir(original_cwd)

        self.assertEqual(len(jobs), 8)
        self.assertEqual({job["provider"] for job in jobs}, {"az", "lv", "ml", "ph"})

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


class ArticleLifecycleTests(unittest.TestCase):
    def test_missing_article_moves_from_active_to_finished_after_threshold(self) -> None:
        active = Stream(Status.active)
        on_hold = Stream(Status.on_hold)
        finished = Stream(Status.finished)
        lifecycle = ArticleLifecycle(
            active,
            on_hold,
            finished,
            Article.create,
            hold_miss_threshold=2,
        )

        article, is_new, is_updated = lifecycle.save(
            {"identifier": "item-1", "title": "Console", "price": 100.0}
        )

        self.assertIsNotNone(article)
        self.assertTrue(is_new)
        self.assertFalse(is_updated)
        self.assertEqual(len(active), 1)

        lifecycle.save(article, to_status=Status.on_hold, at_beginning=False)
        self.assertEqual(len(active), 0)
        self.assertEqual(len(on_hold), 1)
        self.assertEqual(on_hold.get_list()[0].hold_misses, 1)

        lifecycle.save(article, to_status=Status.on_hold, at_beginning=False)
        self.assertEqual(len(on_hold), 0)
        self.assertEqual(len(finished), 1)
        self.assertEqual(finished.get_list()[0].status, Status.finished)


class FetchStrategyConfigTests(unittest.TestCase):
    def test_default_fetch_strategy_is_aiohttp(self) -> None:
        motor = Amazon("macbook", Seller.none, storage_path="tests/amazon.json")

        self.assertEqual(motor.FETCH_STRATEGY, "aiohttp")

    def test_mercado_libre_fetch_strategy_is_browser(self) -> None:
        motor = MercadoLibre("pokemon ds", Category.consolas, storage_path="tests/ml.json")

        self.assertEqual(motor.FETCH_STRATEGY, "browser")
        self.assertEqual(motor.BROWSER_WAIT_SELECTOR, "section.ui-search-results")

    def test_invalid_fetch_strategy_raises_clear_error(self) -> None:
        with self.assertRaisesRegex(ValueError, "FETCH_STRATEGY"):
            Motor._coerce_fetch_strategy("spaceship")


class FetchDelegationTests(unittest.IsolatedAsyncioTestCase):
    async def test_aiohttp_fetch_uses_configured_timeout(self) -> None:
        motor = AioHttpDummyMotor()
        session = CapturingAioHttpSession()

        html = await AioHttpFetcher().fetch(motor, session, "https://example.test")

        self.assertEqual(html, "<html></html>")
        self.assertIsNotNone(session.timeout)
        self.assertEqual(session.timeout.connect, 10)
        self.assertEqual(session.timeout.sock_read, 45)

    async def test_motor_delegates_to_configured_fetcher(self) -> None:
        motor = Amazon("macbook", Seller.none, storage_path="tests/amazon.json")
        fake_fetcher = AsyncMock()
        fake_fetcher.fetch.return_value = "<html></html>"

        with patch("shared.scraping.motor.get_fetcher", return_value=fake_fetcher) as get_fetcher:
            html = await motor._fetch(session=None, url="https://example.test")

        self.assertEqual(html, "<html></html>")
        get_fetcher.assert_called_once_with("aiohttp")
        fake_fetcher.fetch.assert_awaited_once()

    async def test_provider_can_opt_into_browser_strategy_by_config_value(self) -> None:
        motor = Amazon("macbook", Seller.none, storage_path="tests/amazon.json")
        motor.FETCH_STRATEGY = "browser"
        fake_fetcher = AsyncMock()
        fake_fetcher.fetch.return_value = "<html></html>"

        with patch("shared.scraping.motor.get_fetcher", return_value=fake_fetcher) as get_fetcher:
            await motor._fetch(session=None, url="https://example.test")

        get_fetcher.assert_called_once_with("browser")


class BrowserFetcherTests(unittest.IsolatedAsyncioTestCase):
    async def test_browser_fetch_returns_html_when_wait_selector_appears(self) -> None:
        page = FakePage({"section.results": 1}, "<html><section class='results'></section></html>")
        fetcher = BrowserFetcher()
        fetcher._get_context = AsyncMock(return_value=FakeContext(page))
        motor = FetchDummyMotor()

        html = await fetcher.fetch(motor, session=None, url="https://example.test")

        self.assertIn("section", html)
        self.assertIsNone(motor.blocked_reason)
        self.assertTrue(page.closed)

    async def test_browser_fetch_marks_blocked_when_block_selector_appears(self) -> None:
        page = FakePage({"section.blocked": 1})
        fetcher = BrowserFetcher()
        fetcher._get_context = AsyncMock(return_value=FakeContext(page))
        motor = FetchDummyMotor(block_selectors=("section.blocked",))

        html = await fetcher.fetch(motor, session=None, url="https://example.test")

        self.assertIsNone(html)
        self.assertEqual(motor.blocked_reason, "browser_blocked")

    async def test_browser_fetch_marks_timeout_without_content(self) -> None:
        page = FakePage({})
        fetcher = BrowserFetcher()
        fetcher._poll_interval_seconds = 0.01
        fetcher._get_context = AsyncMock(return_value=FakeContext(page))
        motor = FetchDummyMotor(timeout=1)

        html = await fetcher.fetch(motor, session=None, url="https://example.test")

        self.assertIsNone(html)
        self.assertEqual(motor.blocked_reason, "browser_timeout")


class MercadoLibreStabilityTests(unittest.IsolatedAsyncioTestCase):
    async def test_js_gate_marks_scrape_incomplete_and_keeps_active_items(self) -> None:
        html = """
        <html>
          <head><title>Pokemon Ds | MercadoLibre</title></head>
          <body>This page requires JavaScript to work. Please enable JavaScript in your browser to continue.</body>
        </html>
        """
        motor = MercadoLibre("pokemon ds", Category.consolas, storage_path="tests/ml-js-gate.json")
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
        motor = MercadoLibre("pokemon ds", Category.consolas, storage_path="tests/ml-timeout.json")
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
        motor = Amazon("macbook", Seller.none, storage_path="tests/amazon.json")

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
        fixture = Path(
            "https___listado.mercadolibre.com.mx_consolas-videojuegos_consolas_nintendo_usado_new-nintendo-3ds-xl_NoIndex_True.html"
        )
        if not fixture.exists():
            self.skipTest("Mercado Libre root source fixture is not present.")
        html = fixture.read_text(encoding="utf-8", errors="replace")
        url = "https://listado.mercadolibre.com.mx/consolas-videojuegos/consolas/nintendo/usado/new-nintendo-3ds-xl_NoIndex_True"
        motor = MercadoLibre(
            "new nintendo 3ds xl", Category.consolas, storage_path="tests/ml-source.json"
        )

        items, next_url = motor.scrape_page({"content": html, "url": url})

        self.assertEqual(len(items), 48)
        self.assertEqual(items[0]["identifier"], "MLMU3972668090")
        self.assertEqual(
            items[0]["title"], "Nintendo New 3ds Xl Restaurado Con Magia, Leer Descripción"
        )
        self.assertEqual(items[0]["price"], 6000.0)
        self.assertEqual(next_url, f"{url.replace('_NoIndex_True', '_Desde_49_NoIndex_True')}")

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
        motor = MercadoLibre("nintendo", Category.consolas, storage_path="tests/ml-nordic.json")

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
