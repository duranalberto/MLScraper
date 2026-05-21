from __future__ import annotations

import asyncio
import logging
import random
from abc import ABC, abstractmethod
from traceback import format_exc
from typing import Any, Callable, List, Optional, Tuple
from urllib.parse import urlparse

from aiohttp import ClientSession

from shared.articles.article import Article
from shared.articles.lifecycle import ArticleLifecycle
from shared.articles.repository import ArticleRepository
from shared.articles.status import Status
from shared.articles.stream import Stream

from .fetchers import get_fetcher
from . import motor_config
from .motor_config import (
    apply_motor_config,
    coerce_bool,
    coerce_fetch_strategy,
    coerce_int,
    coerce_optional_str,
    coerce_page_delay,
    coerce_string_tuple,
    get_setting,
    lookup_class_config,
)

logger = logging.getLogger(__name__)
_CONFIG_PATH = motor_config.CONFIG_PATH
_load_motor_config = motor_config.load_motor_config


class Motor(ABC):
    PROVIDER_KEY: str | None = None
    PAGE_DELAY_RANGE: Tuple[float, float] | None = None
    FRESH_SESSION_PER_PAGE: bool | None = None
    MAX_RATE_LIMIT_RETRIES: int | None = None
    RATE_LIMIT_SLEEP_CAP: int | None = None
    BLOCKED_BACKOFF_SECONDS: int | None = None
    CONCURRENCY_LIMIT: int | None = None
    FETCH_STRATEGY: str | None = None
    FETCH_TIMEOUT_SECONDS: int | None = None
    BROWSER_WAIT_SELECTOR: str | None = None
    BROWSER_BLOCK_SELECTORS: tuple[str, ...] | None = None
    HOLD_MISS_THRESHOLD: int = 3

    def __init__(
        self,
        search_term: str,
        url: str,
        storage_path: str,
        debug: bool = True,
    ) -> None:
        self.search_term = search_term
        self.url = url
        self.storage_path = storage_path
        self.active = Stream(Status.active)
        self.on_hold = Stream(Status.on_hold)
        self.finished = Stream(Status.finished)
        self.debug = debug
        self.blocked_until: float = 0.0
        self.blocked_reason: str | None = None
        self._scrape_incomplete: bool = False

        self._apply_config()
        self._repository = ArticleRepository(
            self.storage_path,
            self.active,
            self.on_hold,
            self.finished,
            self.create_article,
            self.debug,
        )
        self._lifecycle = ArticleLifecycle(
            self.active,
            self.on_hold,
            self.finished,
            self.create_article,
            self.HOLD_MISS_THRESHOLD,
        )

        self.load_from_file()
        self.is_first_run = len(self.get_all()) == 0

    def _apply_config(self) -> None:
        apply_motor_config(self)

    @staticmethod
    def _lookup_class_config(config: dict[str, Any], class_name: str) -> dict[str, Any]:
        return lookup_class_config(config, class_name)

    def _get_setting(self, key: str, class_config: dict[str, Any]) -> Any:
        return get_setting(self, key, class_config)

    @staticmethod
    def _coerce_page_delay(value: Any) -> Tuple[float, float]:
        return coerce_page_delay(value)

    @staticmethod
    def _coerce_bool(value: Any) -> bool:
        return coerce_bool(value)

    @staticmethod
    def _coerce_int(value: Any) -> int:
        return coerce_int(value)

    @staticmethod
    def _coerce_fetch_strategy(value: Any) -> str:
        return coerce_fetch_strategy(value)

    @staticmethod
    def _coerce_optional_str(value: Any) -> str | None:
        return coerce_optional_str(value)

    @staticmethod
    def _coerce_string_tuple(value: Any) -> tuple[str, ...]:
        return coerce_string_tuple(value)

    async def _fetch(
        self,
        session: ClientSession,
        url: str,
        retries: int = 3,
    ) -> Optional[str]:
        return await get_fetcher(self.fetch_strategy).fetch(
            motor=self,
            session=session,
            url=url,
            retries=retries,
        )

    @property
    def fetch_strategy(self) -> str:
        if self.FETCH_STRATEGY is None:
            raise RuntimeError("FETCH_STRATEGY must be configured before fetching.")
        return self.FETCH_STRATEGY

    async def scrape(
        self,
        caller: Optional[Callable] = None,
        silent: bool = False,
    ) -> None:
        results: List[Article] = []
        current_url: Optional[str] = self.url
        loop = asyncio.get_running_loop()
        self._scrape_incomplete = False

        if self.blocked_until > loop.time():
            if self.debug:
                logger.warning(
                    "Skipping '%s' until %s after a temporary block.",
                    self.search_term,
                    self.blocked_until,
                )
            return
        self.blocked_reason = None

        try:
            if caller and self.is_first_run and not silent:
                logger.info(
                    "%-35s | first run: Telegram notifications will be skipped",
                    self.search_term,
                )

            if self.FRESH_SESSION_PER_PAGE:
                while current_url:
                    async with ClientSession() as session:
                        current_url = await self._scrape_current_page(
                            session, current_url, results, caller, silent
                        )
            else:
                async with ClientSession() as session:
                    while current_url:
                        current_url = await self._scrape_current_page(
                            session, current_url, results, caller, silent
                        )

        except Exception:
            logger.error("Scrape for '%s' crashed:\n%s", self.search_term, format_exc())
            return

        if results or self.active.get_list() or self.on_hold.get_list():
            if not self._scrape_incomplete:
                self._reconcile_missing(results)
            elif self.debug:
                logger.warning(
                    "Skipping missing-item reconciliation for '%s' because the scrape did not complete.",
                    self.search_term,
                )

            await self.save_to_file()
            self.is_first_run = False

            if not silent:
                logger.info(
                    "%-35s | total recorded: %d",
                    self.search_term,
                    len(results),
                )

    @abstractmethod
    def scrape_page(self, body: dict) -> Tuple[List[Any], Optional[str]]:
        """Return (items_list, next_page_url_or_None)."""

    async def _scrape_current_page(
        self,
        session: ClientSession,
        current_url: str,
        results: List[Article],
        caller: Optional[Callable],
        silent: bool,
    ) -> Optional[str]:
        next_url = await self._scrape_page(
            session=session,
            current_url=current_url,
            results=results,
            caller=caller,
            silent=silent,
        )
        if next_url:
            await self._sleep_before_next_page()
        return next_url

    async def _scrape_page(
        self,
        session: ClientSession,
        current_url: str,
        results: List[Article],
        caller: Optional[Callable],
        silent: bool,
    ) -> Optional[str]:
        html = await self._fetch(session, current_url)
        if not html:
            self._scrape_incomplete = True
            self.blocked_reason = self.blocked_reason or "fetch_failed"
            if self.debug:
                logger.warning(
                    "Failed to fetch '%s' for '%s'",
                    current_url,
                    self.search_term,
                )
            return None

        try:
            body = {"content": html, "url": current_url}
            items, next_url = self.scrape_page(body)
        except Exception:
            self._scrape_incomplete = True
            self.blocked_reason = "parse_error"
            logger.error("Error parsing %s:\n%s", current_url, format_exc())
            return None

        items = items or []

        if not silent:
            logger.info(
                "%-35s | found: %3d | next: %s",
                self.search_term,
                len(items),
                "yes" if next_url else "no",
            )

        if not items and next_url:
            self._scrape_incomplete = True
            cooldown = self.BLOCKED_BACKOFF_SECONDS
            if cooldown is not None and cooldown > 0:
                self.mark_blocked("empty_paginated_page", cooldown)
            logger.warning(
                "Empty result page for '%s' at %s with a next page present; stopping pagination.",
                self.search_term,
                current_url,
            )
            return None

        for item in items:
            article, is_new, is_updated = self.save(item)

            if article is not None:
                results.append(article)

                if caller and (is_new or is_updated):
                    b_type = "new_element" if is_new else "is_updated"
                    element = self._article_payload(article)
                    if is_new:
                        element["is_initial_scrape"] = self.is_first_run
                    try:
                        await caller(
                            broadcast_type=b_type,
                            element=element,
                        )
                    except Exception:
                        pass

        return next_url

    def save(
        self,
        item: Any,
        to_status: Status = Status.none,
        at_beginning: bool = True,
    ) -> Tuple[Optional[Article], bool, bool]:
        return self._lifecycle.save(item, to_status, at_beginning)

    @staticmethod
    def is_article(obj: Any) -> bool:
        return isinstance(obj, Article)

    def create_article(self, data: dict) -> Optional[Article]:
        try:
            # Drop 'search_term' if it was loaded from an old JSON file
            # that still has the field.  It is no longer part of Article.
            clean = {k: v for k, v in data.items() if k != "search_term"}
            return Article.create(clean)
        except Exception:
            return None

    def load_from_file(self) -> None:
        self._repository.load()

    def _load_record(self, record: Any, seen_identifiers: set[str]) -> Optional[Article]:
        return self._repository._load_record(record, seen_identifiers)

    async def save_to_file(self) -> None:
        await self._repository.save(self.get_all())

    def _dump_state(self) -> str:
        return self._repository.dump(self.get_all())

    def get_all(self) -> List[Article]:
        return list(self.active) + list(self.on_hold) + list(self.finished)

    def _article_payload(self, article: Article) -> dict:
        """
        Enrich the article dump with motor-level context (search_term)
        for outbound notifications.  search_term lives here, not in the
        stored JSON.
        """
        payload = article.dump()
        payload["search_term"] = self.search_term
        return payload

    def print_compare(self) -> None:
        logger.info("")
        logger.info("Summary for: %s", self.search_term)
        logger.info("  Storage path:      %s", self.storage_path)
        logger.info("  Total in storage:  %d", len(self.get_all()))
        logger.info("  Currently active:  %d", len(self.active))
        logger.info("  Currently on hold: %d", len(self.on_hold))
        logger.info("  Currently finished:%d", len(self.finished))

    @property
    def provider_key(self) -> str:
        return self.PROVIDER_KEY or type(self).__name__

    @property
    def domain(self) -> str:
        host = urlparse(self.url).netloc.lower()
        if host.startswith("www."):
            host = host[4:]
        return host

    def mark_blocked(self, reason: str, cooldown: float | int | None = None) -> None:
        self.blocked_reason = reason
        if cooldown and cooldown > 0:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                return
            self.blocked_until = loop.time() + float(cooldown)

    async def _sleep_before_next_page(self) -> None:
        low, high = self.page_delay_range
        if high <= 0:
            return
        await asyncio.sleep(random.uniform(low, high))

    def _retry_after_delay(self, value: Optional[str]) -> float:
        default = 60.0
        if not value:
            return default

        try:
            seconds = float(value)
        except TypeError, ValueError:
            return default

        return max(0.0, min(seconds, float(self.rate_limit_sleep_cap)))

    @property
    def page_delay_range(self) -> Tuple[float, float]:
        if self.PAGE_DELAY_RANGE is None:
            raise RuntimeError("PAGE_DELAY_RANGE must be configured before pagination sleeps.")
        return self.PAGE_DELAY_RANGE

    @property
    def rate_limit_sleep_cap(self) -> int:
        if self.RATE_LIMIT_SLEEP_CAP is None:
            raise RuntimeError("RATE_LIMIT_SLEEP_CAP must be configured before retry backoff.")
        return self.RATE_LIMIT_SLEEP_CAP

    def _reconcile_missing(self, results: List[Article]) -> None:
        missing_from_active = self.active - results
        missing_from_hold = self.on_hold - results

        for article in missing_from_active:
            self.save(article, to_status=Status.on_hold, at_beginning=False)

        for article in missing_from_hold:
            self.save(article, to_status=Status.on_hold, at_beginning=False)
