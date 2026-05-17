from __future__ import annotations

from typing import Any, Callable, Optional, Tuple

from .article import Article
from .status import Status
from .stream import Stream


class ArticleLifecycle:
    def __init__(
        self,
        active: Stream,
        on_hold: Stream,
        finished: Stream,
        create_article: Callable[[dict], Optional[Article]],
        hold_miss_threshold: int,
    ) -> None:
        self.active = active
        self.on_hold = on_hold
        self.finished = finished
        self.create_article = create_article
        self.hold_miss_threshold = hold_miss_threshold

    def save(
        self,
        item: Any,
        to_status: Status = Status.none,
        at_beginning: bool = True,
    ) -> Tuple[Optional[Article], bool, bool]:
        is_new = is_updated = False

        article = item if isinstance(item, Article) else self.create_article(item)
        if not article:
            return None, False, False

        target = to_status if to_status != Status.none else Status.active

        if target == Status.active:
            return self._save_active(article, at_beginning)

        if target == Status.finished:
            removed_hold = self.on_hold.delete(article)
            removed_active = self.active.delete(article) if removed_hold is None else None
            existing = removed_hold or removed_active or article
            existing.hold_misses = 0
            existing.record_status_history(Status.finished)
            self.finished.add(existing)
            return existing, is_new, is_updated

        if target == Status.on_hold:
            return self._save_on_hold(article, at_beginning)

        return article, is_new, is_updated

    def _save_active(
        self,
        article: Article,
        at_beginning: bool,
    ) -> Tuple[Optional[Article], bool, bool]:
        is_new = is_updated = False
        previously_finished = self.finished.delete(article)
        previously_on_hold = self.on_hold.delete(article)

        if previously_finished is not None:
            previously_finished.record_status_history(Status.active)
            article, is_updated = self._reactivate(previously_finished, article, at_beginning)
            return article, is_new, is_updated

        if previously_on_hold is not None:
            article, is_updated = self._reactivate(previously_on_hold, article, at_beginning)
            return article, is_new, is_updated

        if article not in self.active:
            self.active.add(article, at_beginning)
            is_new = True
        else:
            updated = self.active.update(article)
            if isinstance(updated, Article):
                article = updated
                is_updated = True

        return article, is_new, is_updated

    def _reactivate(
        self,
        existing: Article,
        incoming: Article,
        at_beginning: bool,
    ) -> Tuple[Article, bool]:
        existing.hold_misses = 0
        is_updated = existing.update({"title": incoming.title, "price": incoming.price})
        if existing not in self.active:
            self.active.add(existing, at_beginning)
        return existing, is_updated

    def _save_on_hold(
        self,
        article: Article,
        at_beginning: bool,
    ) -> Tuple[Optional[Article], bool, bool]:
        is_new = is_updated = False
        removed_active = self.active.delete(article)
        if removed_active is not None:
            removed_active.hold_misses = 1
            self.on_hold.add(removed_active, at_beginning)
            return removed_active, is_new, is_updated

        removed_hold = self.on_hold.delete(article)
        if removed_hold is not None:
            removed_hold.hold_misses = (
                removed_hold.hold_misses + 1 if removed_hold.hold_misses else 1
            )
            if removed_hold.hold_misses >= self.hold_miss_threshold:
                removed_hold.record_status_history(Status.finished)
                removed_hold.hold_misses = 0
                self.finished.add(removed_hold, at_beginning)
                return removed_hold, is_new, is_updated
            self.on_hold.add(removed_hold, at_beginning)
            return removed_hold, is_new, is_updated

        article.hold_misses = 1
        self.on_hold.add(article, at_beginning)
        return article, is_new, is_updated
