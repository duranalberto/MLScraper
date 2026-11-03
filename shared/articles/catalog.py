"""Store-scoped canonical article catalog (Identity Map) and cross-search synchronization.

Each store/provider (``az``, ``lv``, ``ml``, ``ph``) owns a single
:class:`ProviderCatalog` instance. All :class:`~shared.scraping.motor.Motor`
instances belonging to the same provider share the canonical :class:`Article`
objects stored in their provider's catalog while maintaining their own
search-scoped :class:`~shared.articles.stream.Stream` memberships
(``active``, ``on_hold``, ``finished``).

This two-tier architecture guarantees:
- **Zero in-memory staleness across searches**: Updating a product's price or
  title in one search immediately updates the shared :class:`Article` reference
  seen by all other overlapping searches of the same store.
- **First-writer-wins deduplication**: Concurrent discovery or price updates of
  the same product across multiple searches of the same store produce at most
  one history entry, one database write, and one notification event.
- **Strict status dominance**: A product's store-global status is ``active`` if
  it is active in *any* enabled search of the store, ``on_hold`` if it is on
  hold in at least one enabled search and active in none, and ``finished`` only
  when all enabled searches tracking the product have finished it.
"""

from __future__ import annotations

import asyncio
from datetime import datetime as datetime_lib
import threading
import time
from typing import Any, Callable, Optional

from utils.db import (
    PersistenceBackend,
    ScrapeRunRecord,
    SearchArticleState,
    SearchRecord,
    StoreSnapshot,
    normalize_provider_key,
)

from .article import Article
from .status import Status
from .stream import Stream


class ProviderCatalog:
    """Per-store Identity Map holding canonical :class:`Article` instances and search memberships."""

    def __init__(
        self,
        provider: str,
        *,
        backend: PersistenceBackend | None = None,
    ) -> None:
        self.provider = normalize_provider_key(provider)
        self.backend = backend
        self.articles_by_id: dict[str, Article] = {}
        self.search_records_by_path: dict[str, SearchRecord] = {}
        self.search_records_by_id: dict[int, SearchRecord] = {}
        self.search_memberships: dict[str, dict[int, SearchArticleState]] = {}
        self._article_locks: dict[str, threading.RLock] = {}
        self._async_locks: dict[str, asyncio.Lock] = {}
        self._catalog_lock = threading.RLock()
        self._hydrated = False
        self._next_synthetic_search_id = -1

    def _get_thread_lock(self, identifier: str) -> threading.RLock:
        with self._catalog_lock:
            lock = self._article_locks.get(identifier)
            if lock is None:
                lock = threading.RLock()
                self._article_locks[identifier] = lock
            return lock

    def get_async_lock(self, identifier: str) -> asyncio.Lock:
        """Return the per-article :class:`asyncio.Lock` for ``identifier``."""
        with self._catalog_lock:
            lock = self._async_locks.get(identifier)
            if lock is None:
                lock = asyncio.Lock()
                self._async_locks[identifier] = lock
            return lock

    def bind_backend(self, backend: PersistenceBackend | None) -> None:
        """Attach or replace the relational :class:`PersistenceBackend`."""
        with self._catalog_lock:
            if self.backend is not backend:
                self.backend = backend
                self._hydrated = False

    def ensure_hydrated(
        self,
        create_article: Callable[[dict[str, Any]], Optional[Article]] = Article.create,
    ) -> None:
        """Bulk-load the store's canonical articles and search memberships from the DB once."""
        with self._catalog_lock:
            if self._hydrated or self.backend is None:
                return
            snapshot = self.backend.load_store_snapshot(self.provider)
            self._apply_snapshot(snapshot, create_article=create_article)
            self._hydrated = True

    def _apply_snapshot(
        self,
        snapshot: StoreSnapshot,
        *,
        create_article: Callable[[dict[str, Any]], Optional[Article]],
    ) -> None:
        for s_path, s_rec in snapshot.searches_by_storage_path.items():
            self.search_records_by_path[s_path] = s_rec
            self.search_records_by_id[s_rec.id] = s_rec

        for row in snapshot.articles:
            article_id = int(row["id"])
            identifier = str(row["identifier"])
            raw_history = [
                {
                    "datetime": str(h["recorded_at"]),
                    **({"title": str(h["title"])} if h.get("title") is not None else {}),
                    **({"price": float(h["price"])} if h.get("price") is not None else {}),
                }
                for h in snapshot.history_by_article_id.get(article_id, [])
            ]
            raw_status_history = [
                {
                    "datetime": str(sh["recorded_at"]),
                    "status": str(sh["status"]),
                }
                for sh in snapshot.status_history_by_article_id.get(article_id, [])
            ]
            status_str = str(row.get("status") or Status.active.value)
            try:
                status_enum = Status(status_str)
            except ValueError:
                status_enum = Status.active

            article_data: dict[str, Any] = {
                "identifier": identifier,
                "title": str(row["title"]),
                "price": float(row["price"]),
                "url": str(row.get("url") or ""),
                "datetime": str(row.get("created_at") or datetime_lib.now()),
                "status": status_enum,
                "history": raw_history,
                "status_history": raw_status_history,
                "hold_misses": int(row.get("hold_misses") or 0),
                "last_updated": row.get("last_updated"),
                "initial_price": (
                    float(row["initial_price"])
                    if row.get("initial_price") is not None
                    else float(row["price"])
                ),
                "lowest_price": (
                    float(row["lowest_price"])
                    if row.get("lowest_price") is not None
                    else float(row["price"])
                ),
                "lowest_price_at": row.get("lowest_price_at"),
                "highest_price": (
                    float(row["highest_price"])
                    if row.get("highest_price") is not None
                    else float(row["price"])
                ),
                "highest_price_at": row.get("highest_price_at"),
                "last_fetched_epoch": float(row.get("last_fetched_epoch") or 0.0),
                "version": int(row.get("version") or 1),
                "db_id": article_id,
            }
            article = create_article(article_data) or Article.create(article_data)
            if article is not None:
                article.status = status_enum
                article.db_id = article_id
                self.articles_by_id[identifier] = article

        for search_id, states in snapshot.search_articles_by_search_id.items():
            for state in states:
                self.search_memberships.setdefault(state.identifier, {})[search_id] = state

    def register_search(
        self,
        *,
        job_id: str,
        storage_path: str,
        resolved_url: str | None = None,
        query_text: str | None = None,
        filter_config: dict[str, Any] | None = None,
        is_enabled: bool = True,
    ) -> SearchRecord:
        """Register or update a search in the catalog (and database if bound)."""
        with self._catalog_lock:
            if self.backend is not None:
                record = self.backend.upsert_search(
                    provider=self.provider,
                    job_id=job_id,
                    storage_path=storage_path,
                    is_enabled=is_enabled,
                    query_text=query_text,
                    resolved_url=resolved_url,
                    filter_config=filter_config,
                )
            else:
                existing = self.search_records_by_path.get(storage_path)
                if existing is not None:
                    existing.job_id = job_id
                    existing.is_enabled = is_enabled
                    existing.query_text = query_text or existing.query_text
                    existing.resolved_url = resolved_url or existing.resolved_url
                    existing.filter_config = filter_config or existing.filter_config
                    record = existing
                else:
                    search_id = self._next_synthetic_search_id
                    self._next_synthetic_search_id -= 1
                    record = SearchRecord(
                        id=search_id,
                        provider=self.provider,
                        job_id=job_id,
                        storage_path=storage_path,
                        is_enabled=is_enabled,
                        is_first_run=True,
                        query_text=query_text,
                        resolved_url=resolved_url,
                        filter_config=filter_config,
                    )

            self.search_records_by_path[storage_path] = record
            self.search_records_by_id[record.id] = record
            return record

    def hydrate_search_streams(
        self,
        *,
        search_id: int,
        active: Stream,
        on_hold: Stream,
        finished: Stream,
    ) -> int:
        """Populate a motor's streams with canonical :class:`Article` pointers from this catalog."""
        with self._catalog_lock:
            active.clear()
            on_hold.clear()
            finished.clear()
            loaded = 0

            for identifier, by_search in self.search_memberships.items():
                state = by_search.get(search_id)
                if state is None:
                    continue
                canonical = self.articles_by_id.get(identifier)
                if canonical is None:
                    continue
                loaded += 1
                self._place_in_search_stream(
                    canonical,
                    search_status=state.status,
                    active=active,
                    on_hold=on_hold,
                    finished=finished,
                    at_beginning=False,
                )
                # Ensure global status reflects strict dominance across searches
                self.recompute_global_status(identifier)

            return loaded

    def get_search_hold_misses(self, search_id: int, identifier: str) -> int:
        """Return the per-search ``hold_misses`` counter for ``identifier`` in ``search_id``."""
        with self._catalog_lock:
            state = self.search_memberships.get(identifier, {}).get(search_id)
            return state.hold_misses if state is not None else 0

    def observe_article(
        self,
        *,
        search_id: int,
        incoming: Article,
        active: Stream,
        on_hold: Stream,
        finished: Stream,
        at_beginning: bool = True,
        fetched_epoch: float | None = None,
    ) -> tuple[Article, bool, bool]:
        """Observe a scraped article in ``search_id`` under the store's Identity Map rules.

        Args:
            search_id: Identifier of the search job observing ``incoming``.
            incoming: Newly parsed :class:`Article` candidate.
            active: The search motor's ``active`` stream.
            on_hold: The search motor's ``on_hold`` stream.
            finished: The search motor's ``finished`` stream.
            at_beginning: Whether newly added articles should be placed at index 0.
            fetched_epoch: Monotonic timestamp when the page response arrived.

        Returns:
            Tuple of ``(canonical_article, is_new_to_store, is_updated_in_store)``.
        """
        identifier = incoming.identifier
        lock = self._get_thread_lock(identifier)
        epoch = (
            fetched_epoch
            if fetched_epoch is not None
            else (incoming.last_fetched_epoch or time.time())
        )
        now_str = str(datetime_lib.now())

        with lock:
            canonical = self.articles_by_id.get(identifier)
            search_rec = self.search_records_by_id.get(search_id)
            is_search_enabled = search_rec.is_enabled if search_rec is not None else True

            # ------------------------------------------------------------------
            # Case 1: Brand-New Product to the Store ("First Writer Wins")
            # ------------------------------------------------------------------
            if canonical is None:
                canonical = incoming
                canonical.status = Status.active
                canonical.hold_misses = 0
                canonical.last_fetched_epoch = max(canonical.last_fetched_epoch, epoch)
                if not canonical.status_history:
                    canonical.record_status_history(Status.active)

                if self.backend is not None:
                    db_id, inserted, existing_row = self.backend.insert_or_get_article(
                        provider=self.provider,
                        identifier=canonical.identifier,
                        title=canonical.title,
                        price=float(canonical.price),
                        initial_price=float(canonical.initial_price or canonical.price),
                        lowest_price=float(canonical.lowest_price or canonical.price),
                        lowest_price_at=canonical.lowest_price_at or str(canonical.datetime),
                        highest_price=float(canonical.highest_price or canonical.price),
                        highest_price_at=canonical.highest_price_at or str(canonical.datetime),
                        url=canonical.url or "",
                        status=Status.active.value,
                        hold_misses=0,
                        created_at=str(canonical.datetime),
                        last_updated=canonical.last_updated,
                        last_fetched_epoch=canonical.last_fetched_epoch,
                        search_id=search_id if search_id > 0 else None,
                        search_status=Status.active.value,
                        search_hold_misses=0,
                        record_initial_status=True,
                    )
                    canonical.db_id = db_id
                    if not inserted and existing_row is not None:
                        # Another process inserted first; synchronize canonical from DB row
                        self._sync_article_from_db_row(canonical, existing_row)
                        self.articles_by_id[identifier] = canonical
                        self._set_search_membership(
                            search_id=search_id,
                            article=canonical,
                            status=Status.active.value,
                            hold_misses=0,
                            seen_at=now_str,
                            is_search_enabled=is_search_enabled,
                        )
                        self._place_in_search_stream(
                            canonical,
                            search_status=Status.active.value,
                            active=active,
                            on_hold=on_hold,
                            finished=finished,
                            at_beginning=at_beginning,
                        )
                        self.recompute_global_status(identifier)
                        return canonical, False, False

                self.articles_by_id[identifier] = canonical
                self._set_search_membership(
                    search_id=search_id,
                    article=canonical,
                    status=Status.active.value,
                    hold_misses=0,
                    seen_at=str(canonical.datetime),
                    is_search_enabled=is_search_enabled,
                )
                self._place_in_search_stream(
                    canonical,
                    search_status=Status.active.value,
                    active=active,
                    on_hold=on_hold,
                    finished=finished,
                    at_beginning=at_beginning,
                )
                return canonical, True, False

            # ------------------------------------------------------------------
            # Case 2: Product Already Exists in Store Catalog
            # ------------------------------------------------------------------
            was_global_finished = canonical.status == Status.finished
            was_global_on_hold = canonical.status == Status.on_hold
            prev_search_state = self.search_memberships.get(identifier, {}).get(search_id)
            was_search_finished = (
                prev_search_state is not None and prev_search_state.status == Status.finished.value
            ) or (identifier in finished)

            # Update per-search membership to active with 0 hold_misses
            self._set_search_membership(
                search_id=search_id,
                article=canonical,
                status=Status.active.value,
                hold_misses=0,
                seen_at=now_str,
                is_search_enabled=is_search_enabled,
            )
            self._place_in_search_stream(
                canonical,
                search_status=Status.active.value,
                active=active,
                on_hold=on_hold,
                finished=finished,
                at_beginning=at_beginning,
            )

            status_history_entry: dict[str, Any] | None = None
            if was_global_finished or was_search_finished:
                if canonical.record_status_history(Status.active):
                    status_history_entry = canonical.status_history[0].dump()
            canonical.status = Status.active
            canonical.hold_misses = 0

            # Rule 3: Out-of-order stale CDN page fetch guard
            if (
                fetched_epoch is not None
                and canonical.last_fetched_epoch > 0.0
                and fetched_epoch < canonical.last_fetched_epoch
            ):
                if (
                    self.backend is not None
                    and canonical.db_id is not None
                    and (was_global_finished or was_global_on_hold)
                ):
                    self.backend.update_article_status(
                        article_id=canonical.db_id,
                        status=Status.active.value,
                        hold_misses=0,
                        status_history_entry=status_history_entry,
                    )
                return canonical, False, False

            canonical.last_fetched_epoch = max(canonical.last_fetched_epoch, epoch)
            if incoming.url:
                canonical.url = incoming.url

            # Rule 2: Compare-And-Swap Price / Title Update
            is_updated = canonical.update({"title": incoming.title, "price": incoming.price})
            if is_updated:
                latest_history = canonical.history[0].dump() if canonical.history else None
                if self.backend is not None and canonical.db_id is not None:
                    cas_ok, db_row = self.backend.cas_update_article(
                        article_id=canonical.db_id,
                        new_title=canonical.title,
                        new_price=float(canonical.price),
                        lowest_price=float(canonical.lowest_price or canonical.price),
                        lowest_price_at=canonical.lowest_price_at,
                        highest_price=float(canonical.highest_price or canonical.price),
                        highest_price_at=canonical.highest_price_at,
                        url=canonical.url or "",
                        status=Status.active.value,
                        hold_misses=0,
                        last_updated=str(canonical.last_updated or now_str),
                        last_fetched_epoch=canonical.last_fetched_epoch,
                        history_entry=latest_history,
                        status_history_entry=status_history_entry,
                    )
                    if not cas_ok:
                        if db_row is not None:
                            self._sync_article_from_db_row(canonical, db_row)
                        return canonical, False, False
                return canonical, False, True

            if (
                self.backend is not None
                and canonical.db_id is not None
                and (was_global_finished or was_global_on_hold or status_history_entry is not None)
            ):
                self.backend.update_article_status(
                    article_id=canonical.db_id,
                    status=Status.active.value,
                    hold_misses=0,
                    last_fetched_epoch=canonical.last_fetched_epoch,
                    status_history_entry=status_history_entry,
                )

            return canonical, False, False

    def transition_search_article(
        self,
        *,
        search_id: int,
        article: Article,
        target_status: Status,
        hold_miss_threshold: int,
        active: Stream,
        on_hold: Stream,
        finished: Stream,
        at_beginning: bool = False,
    ) -> tuple[Article, tuple[int, str, int, dict[str, Any] | None] | None]:
        """Transition ``article`` within ``search_id`` and recompute its store-global status.

        implements Rule 4 (Strict Status Dominance across searches).
        """
        identifier = article.identifier
        lock = self._get_thread_lock(identifier)
        now_str = str(datetime_lib.now())

        with lock:
            canonical = self.articles_by_id.get(identifier)
            if canonical is None:
                canonical = article
                self.articles_by_id[identifier] = canonical

            search_rec = self.search_records_by_id.get(search_id)
            is_search_enabled = search_rec.is_enabled if search_rec is not None else True
            current_state = self.search_memberships.get(identifier, {}).get(search_id)

            if target_status == Status.finished:
                new_search_status = Status.finished.value
                new_search_misses = 0
            elif target_status == Status.on_hold:
                if current_state is not None and current_state.status == Status.on_hold.value:
                    misses = (current_state.hold_misses + 1) if current_state.hold_misses else 1
                elif identifier in on_hold:
                    base_misses = (
                        current_state.hold_misses if current_state else (canonical.hold_misses or 1)
                    )
                    misses = base_misses + 1
                else:
                    misses = 1

                if misses >= hold_miss_threshold:
                    new_search_status = Status.finished.value
                    new_search_misses = 0
                else:
                    new_search_status = Status.on_hold.value
                    new_search_misses = misses
            else:
                new_search_status = Status.active.value
                new_search_misses = 0

            self._set_search_membership(
                search_id=search_id,
                article=canonical,
                status=new_search_status,
                hold_misses=new_search_misses,
                seen_at=current_state.last_seen_at if current_state else now_str,
                is_search_enabled=is_search_enabled,
            )
            self._place_in_search_stream(
                canonical,
                search_status=new_search_status,
                active=active,
                on_hold=on_hold,
                finished=finished,
                at_beginning=at_beginning,
            )

            global_update = self.recompute_global_status(identifier)
            return canonical, global_update

    def recompute_global_status(
        self,
        identifier: str,
    ) -> tuple[int, str, int, dict[str, Any] | None] | None:
        """Compute store-global status via Strict Dominance: ``active > on_hold > finished``."""
        with self._get_thread_lock(identifier):
            canonical = self.articles_by_id.get(identifier)
            if canonical is None:
                return None

            memberships = self.search_memberships.get(identifier, {})
            enabled_states = [s for s in memberships.values() if s.is_search_enabled]
            if not enabled_states:
                enabled_states = list(memberships.values())

            if not enabled_states:
                return None

            previous_global_status = canonical.status
            previous_global_misses = canonical.hold_misses
            status_entry: dict[str, Any] | None = None

            if any(s.status == Status.active.value for s in enabled_states):
                canonical.status = Status.active
                canonical.hold_misses = 0
            elif any(s.status == Status.on_hold.value for s in enabled_states):
                on_hold_misses = [
                    max(1, s.hold_misses)
                    for s in enabled_states
                    if s.status == Status.on_hold.value
                ]
                canonical.status = Status.on_hold
                canonical.hold_misses = min(on_hold_misses) if on_hold_misses else 1
            else:
                canonical.status = Status.finished
                canonical.hold_misses = 0
                if canonical.record_status_history(Status.finished):
                    status_entry = canonical.status_history[0].dump()

            if canonical.db_id is not None and (
                canonical.status != previous_global_status
                or canonical.hold_misses != previous_global_misses
                or status_entry is not None
            ):
                return (
                    canonical.db_id,
                    canonical.status.value,
                    canonical.hold_misses,
                    status_entry,
                )
            return None

    def flush_search_cycle(
        self,
        *,
        search_id: int,
        is_first_run: bool,
        last_status: str,
        blocked_reason: str | None,
        global_status_updates: list[tuple[int, str, int, dict[str, Any] | None]] | None = None,
        scrape_run: ScrapeRunRecord | None = None,
    ) -> None:
        """Persist all search memberships, global status updates, and run telemetry for ``search_id``."""
        if self.backend is None or search_id <= 0:
            return

        now_str = str(datetime_lib.now())
        memberships: list[SearchArticleState] = []
        with self._catalog_lock:
            for by_search in self.search_memberships.values():
                state = by_search.get(search_id)
                if state is not None and state.article_id > 0:
                    memberships.append(state)

            search_rec = self.search_records_by_id.get(search_id)
            if search_rec is not None:
                search_rec.is_first_run = is_first_run
                search_rec.last_status = last_status
                search_rec.blocked_reason = blocked_reason
                search_rec.last_synced_at = now_str

        self.backend.flush_search_cycle(
            search_id=search_id,
            is_first_run=is_first_run,
            last_status=last_status,
            blocked_reason=blocked_reason,
            last_synced_at=now_str,
            memberships=memberships,
            global_status_updates=global_status_updates or [],
            scrape_run=scrape_run,
        )

    def _set_search_membership(
        self,
        *,
        search_id: int,
        article: Article,
        status: str,
        hold_misses: int,
        seen_at: str,
        is_search_enabled: bool = True,
    ) -> SearchArticleState:
        by_search = self.search_memberships.setdefault(article.identifier, {})
        existing = by_search.get(search_id)
        if existing is None:
            state = SearchArticleState(
                search_id=search_id,
                article_id=article.db_id or 0,
                identifier=article.identifier,
                status=status,
                hold_misses=hold_misses,
                first_seen_at=seen_at,
                last_seen_at=seen_at,
                is_search_enabled=is_search_enabled,
            )
            by_search[search_id] = state
            return state

        if article.db_id:
            existing.article_id = article.db_id
        existing.status = status
        existing.hold_misses = hold_misses
        existing.last_seen_at = seen_at
        existing.is_search_enabled = is_search_enabled
        return existing

    @staticmethod
    def _place_in_search_stream(
        article: Article,
        *,
        search_status: str,
        active: Stream,
        on_hold: Stream,
        finished: Stream,
        at_beginning: bool,
    ) -> None:
        """Place ``article`` into the search stream matching ``search_status`` without clobbering global status."""
        saved_global_status = article.status
        saved_global_misses = article.hold_misses
        if search_status == Status.finished.value:
            active.delete(article)
            on_hold.delete(article)
            if article not in finished:
                finished.add(article, at_beginning=at_beginning)
        elif search_status == Status.on_hold.value:
            active.delete(article)
            finished.delete(article)
            if article not in on_hold:
                on_hold.add(article, at_beginning=at_beginning)
        else:
            on_hold.delete(article)
            finished.delete(article)
            if article not in active:
                active.add(article, at_beginning=at_beginning)
        # Stream.add mutates article.status to the stream's status; restore global status if needed
        if saved_global_status != Status.none:
            article.status = saved_global_status
            article.hold_misses = saved_global_misses

    @staticmethod
    def _sync_article_from_db_row(article: Article, row: dict[str, Any]) -> None:
        article.db_id = int(row["id"])
        article.title = str(row["title"])
        article.price = float(row["price"])
        if row.get("url"):
            article.url = str(row["url"])
        if row.get("initial_price") is not None:
            article.initial_price = float(row["initial_price"])
        if row.get("lowest_price") is not None:
            article.lowest_price = float(row["lowest_price"])
        if row.get("lowest_price_at") is not None:
            article.lowest_price_at = str(row["lowest_price_at"])
        if row.get("highest_price") is not None:
            article.highest_price = float(row["highest_price"])
        if row.get("highest_price_at") is not None:
            article.highest_price_at = str(row["highest_price_at"])
        if row.get("last_updated") is not None:
            article.last_updated = str(row["last_updated"])
        if row.get("last_fetched_epoch") is not None:
            article.last_fetched_epoch = max(
                article.last_fetched_epoch,
                float(row["last_fetched_epoch"]),
            )
        if row.get("version") is not None:
            article.version = int(row["version"])


# ---------------------------------------------------------------------------
# Process-Wide Store Catalog Registry
# ---------------------------------------------------------------------------

_CATALOGS: dict[str, ProviderCatalog] = {}
_CATALOGS_LOCK = threading.RLock()


def get_provider_catalog(
    provider: str,
    *,
    backend: PersistenceBackend | None = None,
) -> ProviderCatalog:
    """Return the shared :class:`ProviderCatalog` for ``provider``."""
    key = normalize_provider_key(provider)
    with _CATALOGS_LOCK:
        catalog = _CATALOGS.get(key)
        if catalog is None:
            catalog = ProviderCatalog(key, backend=backend)
            _CATALOGS[key] = catalog
        elif backend is not None and catalog.backend is not backend:
            catalog.bind_backend(backend)
        return catalog


def reset_provider_catalogs() -> None:
    """Clear all in-memory :class:`ProviderCatalog` singletons (used by tests)."""
    with _CATALOGS_LOCK:
        _CATALOGS.clear()
