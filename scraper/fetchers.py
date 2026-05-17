from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from aiohttp import ClientError, ClientSession, ClientTimeout

from utils.headers import get_random_header

logger = logging.getLogger(__name__)


class AioHttpFetcher:
    async def fetch(
        self,
        motor: Any,
        session: ClientSession,
        url: str,
        retries: int = 3,
    ) -> Optional[str]:
        attempt = 0
        rate_limit_hits = 0

        while attempt < retries:
            try:
                async with session.get(
                    url,
                    headers=get_random_header(),
                    timeout=ClientTimeout(connect=10, sock_read=30),
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
                    if resp.status in {403, 404}:
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
            try:
                await page.close()
            except Exception:
                pass

    async def _get_context(self) -> Any:
        async with self._lock:
            if self._context is not None:
                return self._context

            from playwright.async_api import async_playwright

            headers = get_random_header()
            user_agent = headers.pop("User-Agent")
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
                extra_http_headers=headers,
            )
            return self._context

    async def _wait_for_page(self, motor: Any, page: Any) -> Optional[str]:
        timeout = max(1, int(motor.FETCH_TIMEOUT_SECONDS))
        deadline = asyncio.get_running_loop().time() + timeout
        wait_selector = motor.BROWSER_WAIT_SELECTOR

        while asyncio.get_running_loop().time() < deadline:
            if await self._is_blocked(page, motor.BROWSER_BLOCK_SELECTORS):
                motor.mark_blocked("browser_blocked", motor.BLOCKED_BACKOFF_SECONDS)
                return None

            if not wait_selector or await self._selector_exists(page, wait_selector):
                content = await page.content()
                if content and content.strip():
                    return content
                motor.mark_blocked("browser_empty_content", motor.BLOCKED_BACKOFF_SECONDS)
                return None

            await asyncio.sleep(self._poll_interval_seconds)

        motor.mark_blocked("browser_timeout", motor.BLOCKED_BACKOFF_SECONDS)
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


_FETCHERS = {
    "aiohttp": AioHttpFetcher(),
    "browser": BrowserFetcher(),
}


def get_fetcher(strategy: str) -> AioHttpFetcher | BrowserFetcher:
    return _FETCHERS[strategy]
