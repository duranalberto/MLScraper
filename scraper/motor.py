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

from aiohttp import ClientError, ClientSession, ClientTimeout
import yaml

from .article import Article
from .status import Status
from .stream import Stream
from utils.file_manager import read_json_file, write_in_file
from utils.headers import get_random_header

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
    PAGE_DELAY_RANGE: Tuple[float, float] | None = None
    FRESH_SESSION_PER_PAGE: bool | None = None
    MAX_RATE_LIMIT_RETRIES: int | None = None
    RATE_LIMIT_SLEEP_CAP: int | None = None
    BLOCKED_BACKOFF_SECONDS: int | None = None
    CONCURRENCY_LIMIT: int | None = None

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
        self.finished     = Stream(Status.finished)
        self.debug        = debug
        self.blocked_until: float = 0.0

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

    async def _fetch(
        self,
        session: ClientSession,
        url: str,
        retries: int = 3,
    ) -> Optional[str]:
        loop = asyncio.get_running_loop()
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
                        wait = self._retry_after_delay(resp.headers.get("Retry-After"))
                        rate_limit_hits += 1
                        if self.debug:
                            logger.warning(
                                "HTTP %s for %s — backing off for %ss",
                                resp.status,
                                url,
                                wait,
                            )
                        await asyncio.sleep(wait)
                        if rate_limit_hits >= self.MAX_RATE_LIMIT_RETRIES:
                            self.blocked_until = loop.time() + max(wait, float(self.BLOCKED_BACKOFF_SECONDS))
                            if self.debug:
                                logger.warning(
                                    "Giving up on %s after %d rate-limit responses.",
                                    url,
                                    rate_limit_hits,
                                )
                            return None
                        continue
                    if self.debug:
                        logger.warning("HTTP %s for %s", resp.status, url)
                    if resp.status in {403, 404}:
                        break   # Don't retry permanent failures
            except (ClientError, asyncio.TimeoutError):
                if self.debug:
                    logger.warning(
                        "Transient fetch error for %s (attempt %d/%d).",
                        url,
                        attempt + 1,
                        retries,
                    )

            attempt += 1
            if attempt < retries:
                await asyncio.sleep(0.5 * (2 ** attempt))

        return None

    async def scrape(
        self,
        caller: Optional[Callable] = None,
        silent: bool = False,
    ) -> None:
        results: List[Article] = []
        current_url: Optional[str] = self.url
        loop = asyncio.get_running_loop()

        if self.blocked_until > loop.time():
            if self.debug:
                logger.warning(
                    "Skipping '%s' until %s after a temporary block.",
                    self.search_term,
                    self.blocked_until,
                )
            return

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
        
        if results or self.active.get_list():
            deleted = self.active - results
            for d in deleted:
                self.save(d, to_status=Status.finished)

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
            cooldown = self.BLOCKED_BACKOFF_SECONDS
            if cooldown > 0:
                self.blocked_until = asyncio.get_running_loop().time() + cooldown
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

            if article not in self.active and previously_finished is None:
                self.active.add(article, at_beginning)
                is_new = True
            else:
                existing = previously_finished if previously_finished is not None else article
                updated = self.active.update(existing)
                if self.is_article(updated):
                    article = updated
                    is_updated = True

        elif target == Status.finished:
            removed = self.active.delete(article)
            self.finished.add(removed or article)

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

        for data in read_json_file(self.storage_path):
            if isinstance(data, dict):
                identifier = data.get("identifier")
                if identifier in seen_identifiers:
                    logger.warning(
                        "Duplicate identifier '%s' found in '%s' — skipping duplicate record.",
                        identifier,
                        self.storage_path,
                    )
                    continue
                seen_identifiers.add(identifier)
                status_value = data.get("status")
                to_status = Status.finished if status_value == Status.finished.value else Status.active
                self.save(data, to_status=to_status, at_beginning=False)
            else:
                logger.warning(
                    "Skipping non-object record in '%s': %r",
                    self.storage_path,
                    data,
                )

    async def save_to_file(self) -> None:
        self.active.order_by_time()
        self.finished.order_by_time()
        payload = json_dumps(
            [a.dump() for a in self.get_all()], indent=2, ensure_ascii=False
        )
        await write_in_file(self.storage_path, payload)

    def get_all(self) -> List[Article]:
        return self.active + self.finished

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
        logger.info("  Currently finished:%d", len(self.finished))

    @property
    def domain(self) -> str:
        host = urlparse(self.url).netloc.lower()
        if host.startswith("www."):
            host = host[4:]
        return host

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
