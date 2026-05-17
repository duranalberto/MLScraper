from __future__ import annotations

import logging
from json import dumps as json_dumps
from typing import Any, Callable, Iterable, Optional

from .article import Article
from .status import Status
from .stream import Stream
from utils.file_manager import read_json_file, write_in_file

logger = logging.getLogger(__name__)


class ArticleRepository:
    def __init__(
        self,
        storage_path: str,
        active: Stream,
        on_hold: Stream,
        finished: Stream,
        create_article: Callable[[dict], Optional[Article]],
        debug: bool = True,
    ) -> None:
        self.storage_path = storage_path
        self.active = active
        self.on_hold = on_hold
        self.finished = finished
        self.create_article = create_article
        self.debug = debug

    def load(self) -> None:
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

    async def save(self, articles: Iterable[Article]) -> None:
        self.active.order_by_time()
        self.on_hold.order_by_time()
        self.finished.order_by_time()
        await write_in_file(self.storage_path, self.dump(articles))

    @staticmethod
    def dump(articles: Iterable[Article]) -> str:
        return json_dumps(
            [article.dump() for article in articles],
            indent=2,
            ensure_ascii=False,
        )
