from __future__ import annotations

import asyncio
import logging
import random
from abc import ABC, abstractmethod
from json import dumps as json_dumps
from functools import lru_cache
from pathlib import Path
from traceback import format_exc
from typing import Any, Callable, List, Optional, Tuple
from urllib.parse import urlparse

from aiohttp import ClientSession
import yaml

from .article import Article
from .fetchers import get_fetcher
from .status import Status
from .stream import Stream
from utils.file_manager import read_json_file, write_in_file

logger = logging.getLogger(__name__)
_CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "motors.yaml"


@lru_cache(maxsize=1)
def _load_motor_config() -> dict[str, Any]:
    if not _CONFIG_PATH.exists():
        raise FileNotFoundError(
            f"Motor config file not found: '{_CONFIG_PATH.resolve()}'. "
            "Create config/motors.yaml to define scraper policy values."
        )

    with _CONFIG_PATH.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}

    if not isinstance(data, dict):
        raise ValueError(
            f"'{_CONFIG_PATH}' must contain a YAML mapping at the top level."
        )

    return data


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
        self.search_term  = search_term
        self.url          = url
        self.storage_path = storage_path
        self.active       = Stream(Status.active)
        self.on_hold      = Stream(Status.on_hold)
        self.finished     = Stream(Status.finished)
        self.debug        = debug
        self.blocked_until: float = 0.0
        self.blocked_reason: str | None = None
        self._scrape_incomplete: bool = False

        self._apply_config()

        self.load_from_file()

    def _apply_config(self) -> None:
        config = _load_motor_config()
        class_name = type(self).__name__
        class_config = self._lookup_class_config(config, class_name)

        self.PAGE_DELAY_RANGE = self._coerce_page_delay(
            self._get_setting("PAGE_DELAY_RANGE", class_config)
        )
        self.FRESH_SESSION_PER_PAGE = self._coerce_bool(
            self._get_setting("FRESH_SESSION_PER_PAGE", class_config)
        )
        self.MAX_RATE_LIMIT_RETRIES = self._coerce_int(
            self._get_setting("MAX_RATE_LIMIT_RETRIES", class_config)
        )
        self.RATE_LIMIT_SLEEP_CAP = self._coerce_int(
            self._get_setting("RATE_LIMIT_SLEEP_CAP", class_config)
        )
        self.BLOCKED_BACKOFF_SECONDS = self._coerce_int(
            self._get_setting("BLOCKED_BACKOFF_SECONDS", class_config)
        )
        self.CONCURRENCY_LIMIT = self._coerce_int(
            self._get_setting("CONCURRENCY_LIMIT", class_config)
        )
        self.FETCH_STRATEGY = self._coerce_fetch_strategy(
            self._get_setting("FETCH_STRATEGY", class_config)
        )
        self.FETCH_TIMEOUT_SECONDS = self._coerce_int(
            self._get_setting("FETCH_TIMEOUT_SECONDS", class_config)
        )
        self.BROWSER_WAIT_SELECTOR = self._coerce_optional_str(
            self._get_setting("BROWSER_WAIT_SELECTOR", class_config)
        )
        self.BROWSER_BLOCK_SELECTORS = self._coerce_string_tuple(
            self._get_setting("BROWSER_BLOCK_SELECTORS", class_config)
        )

    @staticmethod
    def _lookup_class_config(config: dict[str, Any], class_name: str) -> dict[str, Any]:
        defaults = config.get("defaults", {})
        if defaults and not isinstance(defaults, dict):
            raise ValueError("config/motors.yaml 'defaults' must be a mapping.")

        keys = [class_name, f"providers.{class_name}"]
        motor_config: dict[str, Any] = {}
        for key in keys:
            value = config
            for part in key.split("."):
                if not isinstance(value, dict) or part not in value:
                    value = None
                    break
                value = value[part]
            if isinstance(value, dict):
                motor_config = value
                break

        if not motor_config:
            motor_config = {}

        merged = dict(defaults or {})
        merged.update(motor_config)
        return merged

    def _get_setting(self, key: str, class_config: dict[str, Any]) -> Any:
        subclass_value = type(self).__dict__.get(key, None)
        if subclass_value is not None:
            return subclass_value

        if key in class_config:
            return class_config[key]

        raise KeyError(
            f"Missing motor setting '{key}' for {type(self).__name__}. "
            f"Add it to '{_CONFIG_PATH}' or override it in the implementation."
        )

    @staticmethod
    def _coerce_page_delay(value: Any) -> Tuple[float, float]:
        if isinstance(value, (list, tuple)) and len(value) == 2:
            return float(value[0]), float(value[1])
        raise ValueError(f"PAGE_DELAY_RANGE must be a 2-item list or tuple, got {value!r}.")

    @staticmethod
    def _coerce_bool(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        raise ValueError(f"Expected a boolean value, got {value!r}.")

    @staticmethod
    def _coerce_int(value: Any) -> int:
        if isinstance(value, bool) or value is None:
            raise ValueError(f"Expected an integer value, got {value!r}.")
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Expected an integer value, got {value!r}.") from exc

    @staticmethod
    def _coerce_fetch_strategy(value: Any) -> str:
        if not isinstance(value, str):
            raise ValueError(f"FETCH_STRATEGY must be a string, got {value!r}.")
        strategy = value.strip().lower()
        if strategy not in {"aiohttp", "browser"}:
            raise ValueError(
                f"FETCH_STRATEGY must be one of 'aiohttp' or 'browser', got {value!r}."
            )
        return strategy

    @staticmethod
    def _coerce_optional_str(value: Any) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError(f"Expected a string or null value, got {value!r}.")
        value = value.strip()
        return value or None

    @staticmethod
    def _coerce_string_tuple(value: Any) -> tuple[str, ...]:
        if value is None:
            return ()
        if isinstance(value, str):
            value = [value]
        if isinstance(value, (list, tuple)):
            result = tuple(str(item).strip() for item in value if str(item).strip())
            return result
        raise ValueError(f"Expected a string list value, got {value!r}.")

    async def _fetch(
        self,
        session: ClientSession,
        url: str,
        retries: int = 3,
    ) -> Optional[str]:
        return await get_fetcher(self.FETCH_STRATEGY).fetch(
            motor=self,
            session=session,
            url=url,
            retries=retries,
        )

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
            if self.FRESH_SESSION_PER_PAGE:
                while current_url:
                    async with ClientSession() as session:
                        current_url = await self._scrape_page(
                            session=session,
                            current_url=current_url,
                            results=results,
                            caller=caller,
                            silent=silent,
                        )
                    if current_url:
                        await self._sleep_before_next_page()
            else:
                async with ClientSession() as session:
                    while current_url:
                        current_url = await self._scrape_page(
                            session=session,
                            current_url=current_url,
                            results=results,
                            caller=caller,
                            silent=silent,
                        )
                        if current_url:
                            await self._sleep_before_next_page()

        except Exception:
            logger.error(
                "Scrape for '%s' crashed:\n%s", self.search_term, format_exc()
            )
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

            if not silent:
                logger.info(
                    "%-35s | total recorded: %d",
                    self.search_term,
                    len(results),
                )

    @abstractmethod
    def scrape_page(
        self, body: dict
    ) -> Tuple[List[Any], Optional[str]]:
        """Return (items_list, next_page_url_or_None)."""

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
            if cooldown > 0:
                self.mark_blocked("empty_paginated_page", cooldown)
            logger.warning(
                "Empty result page for '%s' at %s with a next page present; stopping pagination.",
                self.search_term,
                current_url,
            )
            return None

        for item in items:
            article, is_new, is_updated = self.save(item)

            if self.is_article(article):
                results.append(article)

                if caller and (is_new or is_updated):
                    b_type = "new_element" if is_new else "is_updated"
                    try:
                        await caller(
                            broadcast_type=b_type,
                            element=self._article_payload(article),
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
        is_new = is_updated = False

        article = item if self.is_article(item) else self.create_article(item)
        if not article:
            return None, False, False

        target = to_status if to_status != Status.none else Status.active

        if target == Status.active:
            previously_finished = self.finished.delete(article)
            previously_on_hold = self.on_hold.delete(article)

            if previously_finished is not None:
                previously_finished.record_status_history(Status.active)
                previously_finished.hold_misses = 0
                updated = previously_finished.update({"title": article.title, "price": article.price})
                article = previously_finished
                if updated:
                    is_updated = True
                if article not in self.active:
                    self.active.add(article, at_beginning)
                return article, is_new, is_updated

            if previously_on_hold is not None:
                previously_on_hold.hold_misses = 0
                updated = previously_on_hold.update({"title": article.title, "price": article.price})
                article = previously_on_hold
                if updated:
                    is_updated = True
                if article not in self.active:
                    self.active.add(article, at_beginning)
                return article, is_new, is_updated

            if article not in self.active:
                self.active.add(article, at_beginning)
                is_new = True
            else:
                updated = self.active.update(article)
                if self.is_article(updated):
                    article = updated
                    is_updated = True

        elif target == Status.finished:
            removed_hold = self.on_hold.delete(article)
            removed_active = self.active.delete(article) if removed_hold is None else None
            existing = removed_hold or removed_active or article
            existing.hold_misses = 0
            existing.record_status_history(Status.finished)
            self.finished.add(existing)
            article = existing

        elif target == Status.on_hold:
            removed_active = self.active.delete(article)
            if removed_active is not None:
                removed_active.hold_misses = 1
                self.on_hold.add(removed_active, at_beginning)
                return removed_active, is_new, is_updated

            removed_hold = self.on_hold.delete(article)
            if removed_hold is not None:
                removed_hold.hold_misses = removed_hold.hold_misses + 1 if removed_hold.hold_misses else 1
                if removed_hold.hold_misses >= self.HOLD_MISS_THRESHOLD:
                    removed_hold.record_status_history(Status.finished)
                    removed_hold.hold_misses = 0
                    self.finished.add(removed_hold, at_beginning)
                    return removed_hold, is_new, is_updated
                self.on_hold.add(removed_hold, at_beginning)
                return removed_hold, is_new, is_updated

            article.hold_misses = 1
            self.on_hold.add(article, at_beginning)

        return article, is_new, is_updated

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
        seen_identifiers: set[str] = set()
        loaded = 0

        for record in read_json_file(self.storage_path):
            article = self._load_record(record, seen_identifiers)
            if not article:
                continue

            loaded += 1
            if article.status == Status.finished:
                self.finished.add(article, at_beginning=False)
            elif article.status == Status.on_hold:
                self.on_hold.add(article, at_beginning=False)
            else:
                self.active.add(article, at_beginning=False)

        if self.debug:
            logger.info(
                "Loaded %d article(s) from '%s' (active=%d, on_hold=%d, finished=%d).",
                loaded,
                self.storage_path,
                len(self.active),
                len(self.on_hold),
                len(self.finished),
            )

    def _load_record(self, record: Any, seen_identifiers: set[str]) -> Optional[Article]:
        if not isinstance(record, dict):
            logger.warning(
                "Skipping non-object record in '%s': %r",
                self.storage_path,
                record,
            )
            return None

        identifier = record.get("identifier")
        if not identifier or not isinstance(identifier, str):
            logger.warning(
                "Skipping record without a valid identifier in '%s': %r",
                self.storage_path,
                record,
            )
            return None

        if identifier in seen_identifiers:
            logger.warning(
                "Duplicate identifier '%s' found in '%s' — skipping duplicate record.",
                identifier,
                self.storage_path,
            )
            return None
        seen_identifiers.add(identifier)

        article = self.create_article(record)
        if not article:
            logger.warning(
                "Skipping malformed record in '%s': %r",
                self.storage_path,
                record,
            )
            return None

        status_value = record.get("status")
        if status_value == Status.finished.value:
            article.status = Status.finished
            article.hold_misses = 0
        elif status_value == Status.on_hold.value:
            article.status = Status.on_hold
            article.hold_misses = article.hold_misses or 1
        else:
            article.status = Status.active

        return article

    async def save_to_file(self) -> None:
        self.active.order_by_time()
        self.on_hold.order_by_time()
        self.finished.order_by_time()
        payload = self._dump_state()
        await write_in_file(self.storage_path, payload)

    def _dump_state(self) -> str:
        return json_dumps(
            [article.dump() for article in self.get_all()],
            indent=2,
            ensure_ascii=False,
        )

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
        low, high = self.PAGE_DELAY_RANGE
        if high <= 0:
            return
        await asyncio.sleep(random.uniform(low, high))

    def _retry_after_delay(self, value: Optional[str]) -> float:
        default = 60.0
        if not value:
            return default

        try:
            seconds = float(value)
        except (TypeError, ValueError):
            return default

        return max(0.0, min(seconds, float(self.RATE_LIMIT_SLEEP_CAP)))

    def _reconcile_missing(self, results: List[Article]) -> None:
        missing_from_active = self.active - results
        missing_from_hold = self.on_hold - results

        for article in missing_from_active:
            self.save(article, to_status=Status.on_hold, at_beginning=False)

        for article in missing_from_hold:
            self.save(article, to_status=Status.on_hold, at_beginning=False)
