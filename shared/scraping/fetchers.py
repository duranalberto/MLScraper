"""HTTP and headless browser fetching strategies."""

from __future__ import annotations

import asyncio
from contextlib import suppress
import logging
from typing import Any, Optional, Protocol, runtime_checkable

from aiohttp import ClientError, ClientSession, ClientTimeout

from utils.headers import get_random_header

logger = logging.getLogger(__name__)


@runtime_checkable
class FetchTarget(Protocol):
    """Segregated motor interface required by page fetchers (ISP)."""

    FETCH_TIMEOUT_SECONDS: int | None
    MAX_RATE_LIMIT_RETRIES: int | None
    BLOCKED_BACKOFF_SECONDS: int | None
    BROWSER_WAIT_SELECTOR: str | None
    BROWSER_BLOCK_SELECTORS: tuple[str, ...] | None
    debug: bool

    def _retry_after_delay(self, value: Optional[str]) -> float:
        """Compute retry delay seconds from an HTTP ``Retry-After`` header."""
        ...

    def mark_blocked(self, reason: str, cooldown: float | int | None = None) -> None:
        """Record a temporary block reason and optional backoff cooldown."""
        ...


@runtime_checkable
class PageFetcher(Protocol):
    """Strategy interface for fetching raw HTML for a target URL."""

    async def fetch(
        self,
        motor: Any,
        session: ClientSession | None,
        url: str,
        retries: int = 3,
    ) -> Optional[str]:
        """Fetch ``url`` and return raw HTML content, or ``None`` on failure."""
        ...


def _is_liverpool_url(url: str) -> bool:
    return "liverpool.com.mx" in str(url).lower()


def _is_retryable_status(motor: Any, status: int, url: str) -> bool:
    """Return ``True`` when a non-200 HTTP status should be retried for ``motor``."""
    retryable_codes = getattr(motor, "RETRYABLE_STATUS_CODES", ()) or ()
    if status in retryable_codes:
        return True
    if status == 404 and _is_liverpool_url(url):
        return True
    return False


class AioHttpFetcher:
    """Asynchronous HTTP fetcher backed by ``aiohttp.ClientSession``."""

    async def fetch(
        self,
        motor: Any,
        session: ClientSession | None,
        url: str,
        retries: int = 3,
    ) -> Optional[str]:
        if session is None:
            async with ClientSession() as owned_session:
                return await self._fetch_with_session(
                    motor=motor,
                    session=owned_session,
                    url=url,
                    retries=retries,
                )
        return await self._fetch_with_session(
            motor=motor,
            session=session,
            url=url,
            retries=retries,
        )

    async def _fetch_with_session(
        self,
        *,
        motor: Any,
        session: ClientSession,
        url: str,
        retries: int,
    ) -> Optional[str]:
        attempt = 0
        rate_limit_hits = 0

        while attempt < retries:
            try:
                timeout_seconds = max(1, int(motor.FETCH_TIMEOUT_SECONDS))
                async with session.get(
                    url,
                    headers=get_random_header(),
                    timeout=ClientTimeout(
                        connect=min(10, timeout_seconds),
                        sock_read=timeout_seconds,
                    ),
                ) as resp:
                    if resp.status == 200:
                        return await resp.text()
                    if resp.status in {429, 503}:
                        wait = motor._retry_after_delay(resp.headers.get("Retry-After"))
                        rate_limit_hits += 1
                        if motor.debug:
                            logger.warning(
                                "HTTP %s for %s — backing off for %ss",
                                resp.status,
                                url,
                                wait,
                            )
                        await asyncio.sleep(wait)
                        if rate_limit_hits >= motor.MAX_RATE_LIMIT_RETRIES:
                            motor.mark_blocked(
                                f"http_{resp.status}_rate_limited",
                                max(wait, float(motor.BLOCKED_BACKOFF_SECONDS)),
                            )
                            if motor.debug:
                                logger.warning(
                                    "Giving up on %s after %d rate-limit responses.",
                                    url,
                                    rate_limit_hits,
                                )
                            return None
                        continue
                    if motor.debug:
                        logger.warning("HTTP %s for %s", resp.status, url)
                    if _is_retryable_status(motor, resp.status, url):
                        pass
                    elif resp.status in {403, 404}:
                        break
            except ClientError, asyncio.TimeoutError:
                if motor.debug:
                    logger.warning(
                        "Transient fetch error for %s (attempt %d/%d).",
                        url,
                        attempt + 1,
                        retries,
                    )

            attempt += 1
            if attempt < retries:
                await asyncio.sleep(0.5 * (2**attempt))

        return None


class BrowserFetcher:
    """Headless Chromium fetcher backed by Playwright for JS-gated providers."""

    _playwright: Any = None
    _browser: Any = None
    _context: Any = None
    _lock = asyncio.Lock()
    _poll_interval_seconds = 0.25

    async def fetch(
        self,
        motor: Any,
        session: ClientSession | None,
        url: str,
        retries: int = 3,
    ) -> Optional[str]:
        try:
            context = await self._get_context()
            page = await context.new_page()
        except Exception as exc:
            motor.mark_blocked("browser_startup_error", motor.BLOCKED_BACKOFF_SECONDS)
            if motor.debug:
                logger.warning("Browser fetch startup failed for %s: %s", url, exc)
            return None

        try:
            timeout_ms = int(motor.FETCH_TIMEOUT_SECONDS) * 1000
            await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            return await self._wait_for_page(motor, page)
        except Exception as exc:
            reason = (
                "browser_timeout"
                if exc.__class__.__name__ == "TimeoutError"
                else "browser_navigation_error"
            )
            motor.mark_blocked(reason, motor.BLOCKED_BACKOFF_SECONDS)
            if motor.debug:
                logger.warning("Browser fetch failed for %s: %s", url, exc)
            return None
        finally:
            with suppress(Exception):
                await page.close()

    async def close(self) -> None:
        """Close the shared Playwright browser context and Chromium process."""
        async with self._lock:
            context, self._context = self._context, None
            browser, self._browser = self._browser, None
            playwright, self._playwright = self._playwright, None

            if context is not None:
                with suppress(Exception):
                    await context.close()
            if browser is not None:
                with suppress(Exception):
                    await browser.close()
            if playwright is not None:
                with suppress(Exception):
                    await playwright.stop()

    async def _get_context(self) -> Any:
        async with self._lock:
            if self._context is not None:
                return self._context

            from playwright.async_api import async_playwright

            headers = get_random_header()
            user_agent = headers.get("User-Agent", "")
            if "Chrome/" not in user_agent:
                user_agent = (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"
                )
            accept_language = headers.get(
                "Accept-Language",
                "es-MX,es;q=0.9,en-US;q=0.8,en;q=0.7",
            )
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled"],
            )
            self._context = await self._browser.new_context(
                user_agent=user_agent,
                locale="es-MX",
                timezone_id="America/Mexico_City",
                viewport={"width": 1366, "height": 768},
                extra_http_headers={"Accept-Language": accept_language},
            )
            if hasattr(self._context, "add_init_script"):
                await self._context.add_init_script(
                    "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
                )
            return self._context

    async def _wait_for_page(self, motor: Any, page: Any) -> Optional[str]:
        timeout = max(1, int(motor.FETCH_TIMEOUT_SECONDS))
        deadline = asyncio.get_running_loop().time() + timeout
        wait_selector = motor.BROWSER_WAIT_SELECTOR

        while asyncio.get_running_loop().time() < deadline:
            if await self._is_blocked(page, motor.BROWSER_BLOCK_SELECTORS):
                motor.mark_blocked("browser_blocked", motor.BLOCKED_BACKOFF_SECONDS)
                if motor.debug:
                    logger.warning(
                        "Browser fetch blocked for '%s' at %s.",
                        getattr(motor, "job_id", "unknown"),
                        getattr(page, "url", "unknown"),
                    )
                return None

            if not wait_selector or await self._selector_exists(page, wait_selector):
                content = await page.content()
                if content and content.strip():
                    return content
                motor.mark_blocked("browser_empty_content", motor.BLOCKED_BACKOFF_SECONDS)
                if motor.debug:
                    logger.warning(
                        "Browser fetch returned empty content for '%s' at %s.",
                        getattr(motor, "job_id", "unknown"),
                        getattr(page, "url", "unknown"),
                    )
                return None

            await asyncio.sleep(self._poll_interval_seconds)

        motor.mark_blocked("browser_timeout", motor.BLOCKED_BACKOFF_SECONDS)
        if motor.debug:
            logger.warning(
                "Browser fetch timed out waiting for '%s' on '%s' at %s.",
                wait_selector,
                getattr(motor, "job_id", "unknown"),
                getattr(page, "url", "unknown"),
            )
        return None

    async def _is_blocked(self, page: Any, block_selectors: tuple[str, ...]) -> bool:
        for selector in block_selectors:
            if selector.startswith("url*="):
                needle = selector.removeprefix("url*=")
                if needle and needle in str(page.url):
                    return True
                continue
            if await self._selector_exists(page, selector):
                return True
        return False

    @staticmethod
    async def _selector_exists(page: Any, selector: str) -> bool:
        try:
            return await page.locator(selector).count() > 0
        except Exception:
            return False


_FETCHERS: dict[str, PageFetcher] = {
    "aiohttp": AioHttpFetcher(),
    "browser": BrowserFetcher(),
}


def register_fetcher(strategy: str, fetcher: PageFetcher) -> None:
    """Register a custom :class:`PageFetcher` under ``strategy``."""
    key = strategy.strip().lower()
    if not key:
        raise ValueError("Fetcher strategy name cannot be blank.")
    _FETCHERS[key] = fetcher


def get_fetcher(strategy: str) -> PageFetcher:
    """Return the registered :class:`PageFetcher` for ``strategy``."""
    return _FETCHERS[strategy]


async def close_fetchers() -> None:
    """Close any registered fetchers that hold persistent resources."""
    for fetcher in _FETCHERS.values():
        close_fn = getattr(fetcher, "close", None)
        if callable(close_fn):
            result = close_fn()
            if asyncio.iscoroutine(result):
                await result
