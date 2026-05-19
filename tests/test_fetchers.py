from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import AsyncMock, Mock, patch

from aiohttp import ClientError

from shared.scraping.fetchers import AioHttpFetcher, BrowserFetcher


class FetcherDummyMotor:
    FETCH_TIMEOUT_SECONDS = 5
    MAX_RATE_LIMIT_RETRIES = 2
    RATE_LIMIT_SLEEP_CAP = 30
    BLOCKED_BACKOFF_SECONDS = 10
    BROWSER_WAIT_SELECTOR = "section.results"
    BROWSER_BLOCK_SELECTORS: tuple[str, ...] = ()
    debug = False

    def __init__(self) -> None:
        self.blocked_reason: str | None = None
        self.blocked_cooldown: float | int | None = None

    def _retry_after_delay(self, value: str | None) -> float:
        if value is None:
            return 0.0
        return min(float(value), float(self.RATE_LIMIT_SLEEP_CAP))

    def mark_blocked(self, reason: str, cooldown: float | int | None = None) -> None:
        self.blocked_reason = reason
        self.blocked_cooldown = cooldown


class FakeResponse:
    def __init__(self, status: int, text: str = "", headers: dict[str, str] | None = None) -> None:
        self.status = status
        self._text = text
        self.headers = headers or {}

    async def __aenter__(self) -> "FakeResponse":
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        return False

    async def text(self) -> str:
        return self._text


class FakeSession:
    def __init__(self, results: list[FakeResponse | Exception]) -> None:
        self.results = results
        self.calls = 0

    def get(self, *args: Any, **kwargs: Any) -> FakeResponse:
        self.calls += 1
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


class FakeLocator:
    def __init__(self, count: int, should_raise: bool = False) -> None:
        self.count_value = count
        self.should_raise = should_raise

    async def count(self) -> int:
        if self.should_raise:
            raise RuntimeError("selector failed")
        return self.count_value


class FakePage:
    def __init__(
        self,
        *,
        selectors: dict[str, int] | None = None,
        content: str = "<html></html>",
        url: str = "https://example.test",
        goto_error: Exception | None = None,
        selector_error: bool = False,
    ) -> None:
        self.selectors = selectors or {}
        self._content = content
        self.url = url
        self.goto_error = goto_error
        self.selector_error = selector_error
        self.closed = False

    async def goto(self, *args: Any, **kwargs: Any) -> None:
        if self.goto_error:
            raise self.goto_error

    def locator(self, selector: str) -> FakeLocator:
        return FakeLocator(self.selectors.get(selector, 0), self.selector_error)

    async def content(self) -> str:
        return self._content

    async def close(self) -> None:
        self.closed = True


class FakeContext:
    def __init__(self, page: FakePage) -> None:
        self.page = page

    async def new_page(self) -> FakePage:
        return self.page


class AioHttpFetcherTests(unittest.IsolatedAsyncioTestCase):
    async def test_rate_limit_responses_mark_motor_blocked_after_configured_limit(self) -> None:
        motor = FetcherDummyMotor()
        session = FakeSession(
            [
                FakeResponse(429, headers={"Retry-After": "2"}),
                FakeResponse(429, headers={"Retry-After": "3"}),
            ]
        )

        with patch("shared.scraping.fetchers.asyncio.sleep", new=AsyncMock()) as sleep:
            html = await AioHttpFetcher().fetch(motor, session, "https://example.test", retries=5)  # type: ignore[arg-type]

        self.assertIsNone(html)
        self.assertEqual(session.calls, 2)
        self.assertEqual(motor.blocked_reason, "http_429_rate_limited")
        self.assertEqual(motor.blocked_cooldown, 10)
        self.assertEqual(sleep.await_count, 2)

    async def test_403_breaks_without_retrying(self) -> None:
        motor = FetcherDummyMotor()
        session = FakeSession([FakeResponse(403)])

        with patch("shared.scraping.fetchers.asyncio.sleep", new=AsyncMock()) as sleep:
            html = await AioHttpFetcher().fetch(motor, session, "https://example.test", retries=3)  # type: ignore[arg-type]

        self.assertIsNone(html)
        self.assertEqual(session.calls, 1)
        sleep.assert_not_awaited()

    async def test_transient_client_error_retries_and_returns_later_success(self) -> None:
        motor = FetcherDummyMotor()
        session = FakeSession([ClientError("temporary"), FakeResponse(200, "<html>ok</html>")])

        with patch("shared.scraping.fetchers.asyncio.sleep", new=AsyncMock()) as sleep:
            html = await AioHttpFetcher().fetch(motor, session, "https://example.test", retries=2)  # type: ignore[arg-type]

        self.assertEqual(html, "<html>ok</html>")
        self.assertEqual(session.calls, 2)
        sleep.assert_awaited_once()


class BrowserFetcherEdgeTests(unittest.IsolatedAsyncioTestCase):
    async def test_browser_startup_error_marks_blocked(self) -> None:
        motor = FetcherDummyMotor()
        fetcher = BrowserFetcher()
        fetcher._get_context = AsyncMock(side_effect=RuntimeError("no browser"))  # type: ignore[method-assign]

        html = await fetcher.fetch(motor, None, "https://example.test")

        self.assertIsNone(html)
        self.assertEqual(motor.blocked_reason, "browser_startup_error")

    async def test_browser_navigation_timeout_marks_timeout_and_closes_page(self) -> None:
        motor = FetcherDummyMotor()
        page = FakePage(goto_error=TimeoutError("slow"))
        fetcher = BrowserFetcher()
        fetcher._get_context = AsyncMock(return_value=FakeContext(page))  # type: ignore[method-assign]

        html = await fetcher.fetch(motor, None, "https://example.test")

        self.assertIsNone(html)
        self.assertEqual(motor.blocked_reason, "browser_timeout")
        self.assertTrue(page.closed)

    async def test_empty_browser_content_marks_empty_content(self) -> None:
        motor = FetcherDummyMotor()
        page = FakePage(selectors={"section.results": 1}, content="  ")
        fetcher = BrowserFetcher()
        fetcher._get_context = AsyncMock(return_value=FakeContext(page))  # type: ignore[method-assign]

        html = await fetcher.fetch(motor, None, "https://example.test")

        self.assertIsNone(html)
        self.assertEqual(motor.blocked_reason, "browser_empty_content")

    async def test_url_block_selector_does_not_query_locator(self) -> None:
        motor = FetcherDummyMotor()
        motor.BROWSER_BLOCK_SELECTORS = ("url*=account-verification",)
        page = Mock(url="https://example.test/account-verification")

        blocked = await BrowserFetcher()._is_blocked(page, motor.BROWSER_BLOCK_SELECTORS)

        self.assertTrue(blocked)
        page.locator.assert_not_called()

    async def test_selector_errors_are_treated_as_missing_selectors(self) -> None:
        page = FakePage(selector_error=True)

        self.assertFalse(await BrowserFetcher._selector_exists(page, "section.results"))
