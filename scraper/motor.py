from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from json import dumps as json_dumps
from traceback import format_exc
from typing import Any, Callable, List, Optional, Tuple

from aiohttp import ClientError, ClientSession, ClientTimeout

from .article import Article
from .status import Status
from .stream import Stream
from utils.file_manager import read_json_file, write_in_file
from utils.headers import get_random_header

logger = logging.getLogger(__name__)


class Motor(ABC):
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

        self.load_from_file()

    async def _fetch(
        self,
        session: ClientSession,
        url: str,
        retries: int = 3,
    ) -> Optional[str]:
        for attempt in range(retries):
            try:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        return await resp.text()
                    if self.debug:
                        logger.warning("HTTP %s for %s", resp.status, url)
                    if resp.status in {403, 404}:
                        break   # Don't retry permanent failures
            except (ClientError, asyncio.TimeoutError):
                pass

            if attempt < retries - 1:
                await asyncio.sleep(0.5 * (2 ** attempt))

        return None

    async def scrape(
        self,
        caller: Optional[Callable] = None,
        silent: bool = False,
    ) -> None:
        results: List[Article] = []
        current_url: Optional[str] = self.url

        timeout = ClientTimeout(total=45)

        try:
            async with ClientSession(
                headers=get_random_header(), timeout=timeout
            ) as session:
                while current_url:
                    html = await self._fetch(session, current_url)
                    if not html:
                        if self.debug:
                            logger.warning(
                                "Failed to fetch '%s' for '%s'",
                                current_url,
                                self.search_term,
                            )
                        break

                    try:
                        body = {"content": html, "url": current_url}
                        items, next_url = self.scrape_page(body)
                    except Exception:
                        logger.error(
                            "Error parsing %s:\n%s", current_url, format_exc()
                        )
                        break

                    items = items or []

                    if not silent:
                        logger.info(
                            "%-35s | found: %3d | next: %s",
                            self.search_term,
                            len(items),
                            "yes" if next_url else "no",
                        )

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

                    current_url = next_url

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
                existing = previously_finished or article
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
        for data in read_json_file(self.storage_path):
            if isinstance(data, dict):
                self.save(data, at_beginning=False)

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
        print(f"\nSummary for: {self.search_term}")
        print(f"  Storage path:      {self.storage_path}")
        print(f"  Total in storage:  {len(self.get_all())}")
        print(f"  Currently active:  {len(self.active)}")
        print(f"  Currently finished:{len(self.finished)}")