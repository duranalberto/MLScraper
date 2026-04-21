"""
scraper/article.py

Article and ArticleHistory dataclasses.

Changes from previous version
──────────────────────────────
• `search_term` has been removed from Article entirely.
  It was owned by the Motor that scraped it, not by the article itself.
  Storing it on every record was redundant and wasted disk space.
  The Motor passes its own search_term / label wherever it is needed
  (e.g. Telegram messages, broadcast payloads).

• `Article.is_valid_args` no longer requires 'search_term'.

• `Article.dump` no longer serialises 'search_term'.

• `ArticleHistory.dump` is unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from datetime import datetime as datetime_lib
from typing import Any, Dict, List, Optional, Self

from .status import Status


# ---------------------------------------------------------------------------
# ArticleHistory
# ---------------------------------------------------------------------------

@dataclass
class ArticleHistory:
    datetime: str
    title:    Optional[str] = None
    price:    Optional[str] = None

    def __str__(self) -> str:
        return f"[{self.datetime}] - {self.title}  ${self.price}"

    def dump(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {"datetime": self.datetime}
        if self.title is not None:
            d["title"] = self.title
        if self.price is not None:
            d["price"] = self.price
        return d

    @staticmethod
    def create(args: Dict[str, Any]) -> Optional[ArticleHistory]:
        if "datetime" not in args or not args["datetime"]:
            return None
        if "title" not in args and "price" not in args:
            return None
        return ArticleHistory(
            datetime=args["datetime"],
            title=args.get("title"),
            price=args.get("price"),
        )


# ---------------------------------------------------------------------------
# Article
# ---------------------------------------------------------------------------

@dataclass
class Article:
    identifier:   str
    title:        str
    price:        float
    url:          Optional[str]  = None
    datetime:     str            = field(default_factory=lambda: str(datetime_lib.now()))
    status:       Status         = Status.none
    history:      List[ArticleHistory] = field(default_factory=list)
    last_updated: Optional[str]  = None

    def __post_init__(self) -> None:
        self.history = self._load_history(self.history)

    # ------------------------------------------------------------------
    # Identity / comparison
    # ------------------------------------------------------------------

    def __str__(self) -> str:
        return f"[{self.datetime}]  {self.title}  ${self.price}"

    def __repr__(self) -> str:
        return self.identifier

    def __hash__(self) -> int:
        return hash(self.identifier)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Article):
            return self.identifier == other.identifier
        return NotImplemented

    # ------------------------------------------------------------------
    # History helpers
    # ------------------------------------------------------------------

    def _load_history(self, raw: list, fix: bool = False) -> List[ArticleHistory]:
        history: List[ArticleHistory] = []
        for item in (raw or []):
            ah = ArticleHistory.create(item)
            if ah:
                history.append(ah)

        if fix:
            if len(history) == 1:
                history[0].datetime = self.datetime
            elif len(history) > 1:
                history.sort(key=lambda x: x.datetime, reverse=True)
                history[-1].datetime = self.datetime

        return history

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------

    def update(self, to_update: Dict[str, Any]) -> bool:
        """
        Apply title/price changes and record them in history.
        Returns True if any field actually changed.
        """
        keys = ("title", "price")
        changes = {
            k: to_update[k]
            for k in keys
            if k in to_update and getattr(self, k) != to_update[k]
        }

        if not changes:
            return False

        for k, v in changes.items():
            setattr(self, k, v)

        is_first = not self.history
        changes["datetime"] = self.datetime if is_first else self.last_updated
        ah = ArticleHistory.create(changes)
        if ah:
            self.last_updated = str(datetime_lib.now())
            self.history.insert(0, ah)

        return True

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def dump(self) -> Dict[str, Any]:
        """
        Serialise to a dict suitable for JSON storage.
        `search_term` is intentionally omitted — it belongs to the Motor,
        not to individual articles.
        """
        d: Dict[str, Any] = {
            "identifier": self.identifier,
            "title":      self.title,
            "price":      self.price,
            "url":        self.url,
            "datetime":   str(self.datetime),
            "status":     self.status,
        }
        if self.history:
            d["last_updated"] = self.last_updated
            d["history"] = [ah.dump() for ah in self.history]
        return d

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @staticmethod
    def is_valid_args(args: Dict[str, Any]) -> bool:
        # Required fields (no default): identifier, title, price
        required = {"identifier", "title", "price"}
        return required.issubset(args.keys())

    @staticmethod
    def create(args: Dict[str, Any]) -> Optional[Article]:
        if not Article.is_valid_args(args):
            return None
        # Drop unknown keys so the dataclass constructor doesn't choke
        known = {f.name for f in fields(Article)}
        return Article(**{k: v for k, v in args.items() if k in known})