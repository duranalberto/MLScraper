"""Article lifecycle state transitions supporting both local streams and store catalogs."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, Optional, Tuple

from .article import Article
from .status import Status
from .stream import Stream

if TYPE_CHECKING:
    from .catalog import ProviderCatalog


class ArticleLifecycle:
    """Manage active, on_hold, and finished transitions for a search motor.

    When ``catalog`` is provided, article observation and status transitions
    are synchronized through the store-wide :class:`ProviderCatalog` Identity
    Map (enforcing First-Writer-Wins deduplication, Compare-And-Swap updates,
    and Strict Status Dominance across searches). When ``catalog`` is ``None``,
    transitions operate purely on the local streams.
    """

    def __init__(
        self,
        active: Stream,
        on_hold: Stream,
        finished: Stream,
        create_article: Callable[[dict], Optional[Article]],
        hold_miss_threshold: int,
        *,
        catalog: ProviderCatalog | None = None,
        search_id: int = 0,
    ) -> None:
        self.active = active
        self.on_hold = on_hold
        self.finished = finished
        self.create_article = create_article
        self.hold_miss_threshold = hold_miss_threshold
        self.catalog = catalog
        self.search_id = search_id
        self.pending_global_updates: list[tuple[int, str, int, dict[str, Any] | None]] = []

    def consume_pending_global_updates(self) -> list[tuple[int, str, int, dict[str, Any] | None]]:
        """Return and clear pending store-global status updates accumulated during reconciliation."""
        updates = list(self.pending_global_updates)
        self.pending_global_updates.clear()
        return updates

    def save(
        self,
        item: Any,
        to_status: Status = Status.none,
        at_beginning: bool = True,
        *,
        fetched_epoch: float | None = None,
    ) -> Tuple[Optional[Article], bool, bool]:
        is_new = is_updated = False

        article = item if isinstance(item, Article) else self.create_article(item)
        if not article:
            return None, False, False

        target = to_status if to_status != Status.none else Status.active

        if self.catalog is not None:
            if target == Status.active:
                return self.catalog.observe_article(
                    search_id=self.search_id,
                    incoming=article,
                    active=self.active,
                    on_hold=self.on_hold,
                    finished=self.finished,
                    at_beginning=at_beginning,
                    fetched_epoch=fetched_epoch,
                )

            if target in (Status.on_hold, Status.finished):
                canonical, global_update = self.catalog.transition_search_article(
                    search_id=self.search_id,
                    article=article,
                    target_status=target,
                    hold_miss_threshold=self.hold_miss_threshold,
                    active=self.active,
                    on_hold=self.on_hold,
                    finished=self.finished,
                    at_beginning=at_beginning,
                )
                if global_update is not None:
                    self.pending_global_updates.append(global_update)
                return canonical, False, False

            return article, False, False

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
