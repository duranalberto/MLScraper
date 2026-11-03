"""Base scraping motor orchestrating fetch, strategy-based page parsing, and persistence."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime as datetime_lib
import random
import time
from abc import ABC
from traceback import format_exc
from typing import Any, Callable, List, Optional, Tuple
from urllib.parse import urlparse

from aiohttp import ClientSession

from shared.articles.article import Article
from shared.articles.catalog import ProviderCatalog, get_provider_catalog
from shared.articles.lifecycle import ArticleLifecycle
from shared.articles.repository import ArticleRepository
from shared.articles.status import Status
from shared.articles.stream import Stream
from utils.db import ScrapeRunRecord, get_persistence_backend

from . import motor_config
from .fetchers import get_fetcher
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
from .page_strategy import PageScrapeResult, PageScrapeStrategy

logger = logging.getLogger(__name__)
_CONFIG_PATH = motor_config.CONFIG_PATH
_load_motor_config = motor_config.load_motor_config


class Motor(ABC):
    """Shared scraping motor that coordinates fetching, page strategies, and article state."""

    PROVIDER_KEY: str | None = None
    PAGE_STRATEGY: PageScrapeStrategy | None = None
    RETRYABLE_STATUS_CODES: tuple[int, ...] = ()
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
        job_id: str,
        url: str,
        storage_path: str,
        debug: bool = True,
        *,
        page_strategy: PageScrapeStrategy | None = None,
        repository: ArticleRepository | None = None,
        lifecycle: ArticleLifecycle | None = None,
        catalog: ProviderCatalog | None = None,
        query_text: str | None = None,
        filter_config: dict[str, Any] | None = None,
    ) -> None:
        self.job_id = job_id
        self.url = url
        self.storage_path = storage_path
        self.query_text = query_text
        self.filter_config = filter_config
        self.active = Stream(Status.active)
        self.on_hold = Stream(Status.on_hold)
        self.finished = Stream(Status.finished)
        self.debug = debug
        self.blocked_until: float = 0.0
        self.blocked_reason: str | None = None
        self._scrape_incomplete: bool = False
        self._last_page_fetched_epoch: float | None = None
        self._cycle_pages_fetched: int = 0
        self._cycle_new_count: int = 0
        self._cycle_updated_count: int = 0
        self._cycle_missing_count: int = 0
        self.page_strategy: PageScrapeStrategy | None = (
            page_strategy if page_strategy is not None else self.PAGE_STRATEGY
        )

        self._apply_config()

        resolved_catalog = catalog
        if resolved_catalog is None and repository is None and lifecycle is None:
            backend = get_persistence_backend()
            if backend is not None:
                resolved_catalog = get_provider_catalog(self.provider_key, backend=backend)

        self.catalog: ProviderCatalog | None = resolved_catalog
        self.search_id: int = 0
        if self.catalog is not None:
            self.catalog.ensure_hydrated(self.create_article)
            search_rec = self.catalog.register_search(
                job_id=self.job_id,
                storage_path=self.storage_path,
                resolved_url=self.url,
                query_text=self.query_text,
                filter_config=self.filter_config,
                is_enabled=True,
            )
            self.search_id = search_rec.id

        self._repository = repository or ArticleRepository(
            self.storage_path,
            self.active,
            self.on_hold,
            self.finished,
            self.create_article,
            self.debug,
            catalog=self.catalog,
            search_id=self.search_id,
        )
        self._lifecycle = lifecycle or ArticleLifecycle(
            self.active,
            self.on_hold,
            self.finished,
            self.create_article,
            self.HOLD_MISS_THRESHOLD,
            catalog=self.catalog,
            search_id=self.search_id,
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
        session: ClientSession | None,
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
        self._cycle_pages_fetched = 0
        self._cycle_new_count = 0
        self._cycle_updated_count = 0
        self._cycle_missing_count = 0
        cycle_started_at = str(datetime_lib.now())
        cycle_start_clock = time.time()

        if self.blocked_until > loop.time():
            if self.debug:
                logger.warning(
                    "Skipping '%s' until %s after a temporary block.",
                    self.job_id,
                    self.blocked_until,
                )
            return
        self.blocked_reason = None

        try:
            if caller and self.is_first_run and not silent:
                logger.info(
                    "%-35s | first run: Telegram notifications will be skipped",
                    self.job_id,
                )

            if self.FETCH_STRATEGY == "browser":
                while current_url:
                    current_url = await self._scrape_current_page(
                        None, current_url, results, caller, silent
                    )
            elif self.FRESH_SESSION_PER_PAGE:
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
            logger.error("Scrape for '%s' crashed:\n%s", self.job_id, format_exc())
            return

        self._last_cycle_started_at = cycle_started_at
        self._last_cycle_start_clock = cycle_start_clock
        self._last_cycle_scraped_count = len(results)

        if results or self.active.get_list() or self.on_hold.get_list():
            if not self._scrape_incomplete:
                self._reconcile_missing(results)
            elif self.debug:
                logger.warning(
                    "Skipping missing-item reconciliation for '%s' because the scrape did not complete.",
                    self.job_id,
                )

            self.is_first_run = False
            await self.save_to_file()

            if not silent:
                logger.info(
                    "%-35s | total recorded: %d",
                    self.job_id,
                    len(results),
                )
        elif self.catalog is not None and self.catalog.backend is not None and self.search_id > 0:
            await self.save_to_file()

    def scrape_page(self, body: dict) -> Tuple[List[Any], Optional[str]]:
        """Execute the configured :class:`PageScrapeStrategy` and return ``(items, next_url)``."""
        if self.page_strategy is None:
            raise NotImplementedError(
                f"{type(self).__name__} must configure 'page_strategy' or override 'scrape_page'."
            )
        content = body.get("content", "")
        current_url = body.get("url", self.url)
        result = self.page_strategy.parse_page(
            content,
            current_url,
            job_id=self.job_id,
        )
        return self._apply_page_scrape_result(result, current_url=current_url)

    def _apply_page_scrape_result(
        self,
        result: PageScrapeResult,
        *,
        current_url: str,
    ) -> Tuple[List[Any], Optional[str]]:
        """Apply block and completeness state from a :class:`PageScrapeResult`."""
        if result.blocked_reason:
            self._scrape_incomplete = True
            self.mark_blocked(result.blocked_reason, self.BLOCKED_BACKOFF_SECONDS)
            if self.debug:
                logger.warning(
                    "%s returned a blocked/gated page (%s) for '%s' at %s.",
                    type(self).__name__,
                    result.blocked_reason,
                    self.job_id,
                    current_url,
                )
            return result.items, None

        if result.incomplete_reason or result.incomplete:
            self._scrape_incomplete = True
            if result.incomplete_reason and not result.incomplete:
                self.blocked_reason = result.incomplete_reason
            elif result.incomplete_reason and self.PROVIDER_KEY == "ml":
                self.blocked_reason = result.incomplete_reason
            if self.debug and result.incomplete_reason:
                logger.warning(
                    "%s returned an incomplete page (%s) for '%s' at %s.",
                    type(self).__name__,
                    result.incomplete_reason,
                    self.job_id,
                    current_url,
                )
            return result.items, None

        return result.items, result.next_url

    async def _scrape_current_page(
        self,
        session: ClientSession | None,
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
        session: ClientSession | None,
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
                    self.job_id,
                )
            return None

        self._last_page_fetched_epoch = time.time()
        self._cycle_pages_fetched += 1

        try:
            body = {"content": html, "url": current_url}
            parsed_page = self.scrape_page(body)
            if isinstance(parsed_page, PageScrapeResult):
                items, next_url = self._apply_page_scrape_result(
                    parsed_page,
                    current_url=current_url,
                )
            else:
                items, next_url = parsed_page
        except Exception:
            self._scrape_incomplete = True
            self.blocked_reason = "parse_error"
            logger.error("Error parsing %s:\n%s", current_url, format_exc())
            return None

        items = items or []

        if not silent:
            logger.info(
                "%-35s | found: %3d | next: %s",
                self.job_id,
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
                self.job_id,
                current_url,
            )
            return None

        for item in items:
            article, is_new, is_updated = self.save(item)

            if article is not None:
                results.append(article)
                if is_new:
                    self._cycle_new_count += 1
                if is_updated:
                    self._cycle_updated_count += 1

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
        *,
        fetched_epoch: float | None = None,
    ) -> Tuple[Optional[Article], bool, bool]:
        resolved_epoch = (
            fetched_epoch if fetched_epoch is not None else self._last_page_fetched_epoch
        )
        if self.catalog is not None:
            return self._lifecycle.save(
                item,
                to_status,
                at_beginning,
                fetched_epoch=resolved_epoch,
            )
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
        if self.catalog is not None and self.catalog.backend is not None and self.search_id > 0:
            try:
                now_loop = asyncio.get_running_loop().time()
            except RuntimeError:
                now_loop = 0.0
            cycle_status = (
                "blocked"
                if self.blocked_reason and self.blocked_until > now_loop
                else ("incomplete" if self._scrape_incomplete else "ok")
            )
            started_at = getattr(self, "_last_cycle_started_at", str(datetime_lib.now()))
            start_clock = getattr(self, "_last_cycle_start_clock", time.time())
            scraped_count = getattr(self, "_last_cycle_scraped_count", len(self.active))
            run_record = ScrapeRunRecord(
                search_id=self.search_id,
                provider=self.provider_key,
                started_at=started_at,
                finished_at=str(datetime_lib.now()),
                duration_s=round(max(0.0, time.time() - start_clock), 4),
                pages_fetched=self._cycle_pages_fetched,
                scraped_count=scraped_count,
                new_count=self._cycle_new_count,
                updated_count=self._cycle_updated_count,
                missing_count=self._cycle_missing_count,
                status=cycle_status,
                error_reason=self.blocked_reason,
            )
            await self._repository.save(
                self.get_all(),
                is_first_run=self.is_first_run,
                last_status=cycle_status,
                blocked_reason=self.blocked_reason,
                global_status_updates=self._lifecycle.consume_pending_global_updates(),
                scrape_run=run_record,
            )
            return

        await self._repository.save(self.get_all())

    def _dump_state(self) -> str:
        return self._repository.dump(self.get_all())

    def get_all(self) -> List[Article]:
        return list(self.active) + list(self.on_hold) + list(self.finished)

    def _article_payload(self, article: Article) -> dict:
        """
        Enrich the article dump with motor-level context for notifications.

        ``job_id`` and ``provider`` identify the configured monitor that found
        the article; neither value belongs in stored product JSON.
        """
        payload = article.dump()
        payload["job_id"] = self.job_id
        payload["provider"] = self.provider_key
        if article.db_id is not None:
            payload["article_id"] = article.db_id
        if self.search_id > 0:
            payload["search_id"] = self.search_id
        if article.initial_price is not None:
            payload["initial_price"] = article.initial_price
        if article.lowest_price is not None:
            payload["lowest_price"] = article.lowest_price
        if article.highest_price is not None:
            payload["highest_price"] = article.highest_price
        return payload

    def print_compare(self) -> None:
        logger.info("")
        logger.info("Summary for: %s", self.job_id)
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
        self._cycle_missing_count = len(missing_from_active) + len(missing_from_hold)

        for article in missing_from_active:
            self.save(article, to_status=Status.on_hold, at_beginning=False)

        for article in missing_from_hold:
            self.save(article, to_status=Status.on_hold, at_beginning=False)
