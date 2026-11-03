"""In-memory article collection with $O(1)$ identifier indexing."""

from __future__ import annotations

import logging
from typing import Iterable, List, Optional

from .article import Article
from .status import Status

logger = logging.getLogger(__name__)


class Stream:
    """Ordered article collection indexed by ``article.identifier`` for $O(1)$ lookups."""

    def __init__(self, status: Status = Status.none, _list: Optional[List[Article]] = None) -> None:
        self.status = status
        self._list: List[Article] = []
        self._index: dict[str, Article] = {}
        if _list:
            for article in _list:
                if isinstance(article, Article) and article.identifier not in self._index:
                    self._list.append(article)
                    self._index[article.identifier] = article

    def __iter__(self):
        """Allows: ``for article in stream:``"""
        return iter(self._list)

    def __contains__(self, item: object) -> bool:
        """Allows: ``if article in stream:`` in $O(1)$ average time."""
        if isinstance(item, Article):
            return item.identifier in self._index
        return item in self._list

    def __len__(self) -> int:
        """Allows: ``len(stream)``"""
        return len(self._list)

    def __bool__(self) -> bool:
        """Allows: ``if stream:``"""
        return len(self._list) > 0

    def __add__(self, other: Iterable[Article]) -> List[Article]:
        """Allows: ``combined = stream1 + stream2``"""
        if isinstance(other, Stream):
            return self._list + other.get_list()
        return self._list + list(other)

    def __sub__(self, other: Iterable[Article]) -> List[Article]:
        """Return items in ``self`` that are not in ``other`` in $O(N + M)$ time."""
        if isinstance(other, Stream):
            other_ids = set(other._index.keys())
        else:
            other_ids = {item.identifier for item in other if isinstance(item, Article)}
        return [item for item in self._list if item.identifier not in other_ids]

    def add(self, article: Article, at_beginning: bool = False) -> Optional[Article]:
        """Insert ``article`` into the stream if its identifier is not already present."""
        if article:
            article.status = self.status
            if article.identifier not in self._index:
                self._index[article.identifier] = article
                if at_beginning:
                    self._list.insert(0, article)
                else:
                    self._list.append(article)
                return article
        return None

    def update(self, article: Article) -> Optional[Article]:
        """Update an existing article in the stream in $O(1)$ lookup time if changed."""
        if article:
            target = self._index.get(article.identifier)
            if target is not None:
                was_updated = target.update({"title": article.title, "price": article.price})
                return target if was_updated else None
        return None

    def extend(self, _list: List[Article]) -> None:
        """Add multiple articles to the stream."""
        for article in _list:
            self.add(article)

    def delete(self, article: Article) -> Optional[Article]:
        """Remove and return the matching article if present ($O(1)$ miss check)."""
        if not article:
            return None
        to_remove = self._index.pop(article.identifier, None)
        if to_remove is not None:
            try:
                self._list.remove(to_remove)
            except ValueError:
                pass
            return to_remove
        return None

    def clear(self) -> None:
        """Remove all articles from the stream."""
        self._list.clear()
        self._index.clear()

    def get_list(self) -> List[Article]:
        """Return the underlying ordered list of articles."""
        return self._list

    def order_by_time(self) -> None:
        """Sort articles by ``datetime`` attribute in descending order."""
        self._list.sort(key=lambda x: x.datetime, reverse=True)

    def print_(self) -> None:
        for e in self._list:
            logger.info("%s - %s", e.title, e.status)
