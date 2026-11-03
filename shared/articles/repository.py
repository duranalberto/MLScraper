"""Article persistence repository supporting injectable storage readers and writers."""

from __future__ import annotations

import asyncio
from json import dumps as json_dumps
import logging
from typing import Any, Awaitable, Callable, Iterable, Optional

from utils.file_manager import read_json_file, write_in_file

from .article import Article
from .status import Status
from .stream import Stream

logger = logging.getLogger(__name__)

StorageReader = Callable[[str], list[Any]]
StorageWriter = Callable[[str, str], Awaitable[None]]


class ArticleRepository:
    """Persist and restore article streams with injectable I/O callables."""

    def __init__(
        self,
        storage_path: str,
        active: Stream,
        on_hold: Stream,
        finished: Stream,
        create_article: Callable[[dict], Optional[Article]],
        debug: bool = True,
        *,
        reader: StorageReader | None = None,
        writer: StorageWriter | None = None,
    ) -> None:
        self.storage_path = storage_path
        self.active = active
        self.on_hold = on_hold
        self.finished = finished
        self.create_article = create_article
        self.debug = debug
        self._reader = reader
        self._writer = writer

    def load(self) -> None:
        seen_identifiers: set[str] = set()
        loaded = 0
        read_fn = self._reader or read_json_file

        for record in read_fn(self.storage_path):
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

    async def save(self, articles: Iterable[Article]) -> None:
        self.active.order_by_time()
        self.on_hold.order_by_time()
        self.finished.order_by_time()
        snapshot = list(articles)
        loop = asyncio.get_running_loop()
        dumped = await loop.run_in_executor(None, self.dump, snapshot)
        write_fn = self._writer or write_in_file
        await write_fn(self.storage_path, dumped)

    @staticmethod
    def dump(articles: Iterable[Article]) -> str:
        return json_dumps(
            [article.dump() for article in articles],
            indent=2,
            ensure_ascii=False,
        )
