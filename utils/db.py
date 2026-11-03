"""Relational database engine, 8-table DDL schema, and persistence backends.

This module implements the relational persistence layer for MLScraper across
eight tables:

1. ``articles``: Store-global canonical product records keyed by
   ``(provider, identifier)`` with price watermarks (``initial_price``,
   ``lowest_price``, ``highest_price``), monotonic fetch epoch guard
   (``last_fetched_epoch``), and optimistic concurrency counter (``version``).
2. ``article_history``: Chronological price and title change log per article.
3. ``article_status_history``: Store-global ``active`` / ``finished`` lifecycle
   transition log per article.
4. ``searches``: Configured and historical search jobs with query/filter
   configuration, active/archived flag (``is_enabled``), and cycle status.
5. ``search_articles``: Many-to-many join table linking searches to canonical
   store articles with per-search ``status`` and ``hold_misses``.
6. ``notification_events``: Audit and idempotency log of dispatched alerts.
7. ``scrape_runs``: Per-cycle execution telemetry and anti-bot block diagnostics.
8. ``provider_url_cache``: Persistent cache of resolved provider URL tokens
   (such as Liverpool's encrypted seller-filtered URL segments).
"""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime as datetime_lib
import json
import logging
import os
from pathlib import Path
import sqlite3
import threading
from typing import Any, Iterator, Optional, Protocol, Sequence, runtime_checkable

import pymysql
from pymysql.cursors import DictCursor

logger = logging.getLogger(__name__)

MAX_DB_HISTORY = 100

PROVIDER_STORAGE_PREFIX_TO_KEY: dict[str, str] = {
    "amazon": "az",
    "liverpool": "lv",
    "mercado_libre": "ml",
    "palacio_de_hierro": "ph",
    "az": "az",
    "lv": "lv",
    "ml": "ml",
    "ph": "ph",
}


def normalize_provider_key(provider_or_path: str) -> str:
    """Normalize a provider key or storage path prefix to canonical short key."""
    cleaned = str(provider_or_path or "").strip().lower()
    if "/" in cleaned:
        cleaned = cleaned.split("/", 1)[0]
    return PROVIDER_STORAGE_PREFIX_TO_KEY.get(cleaned, cleaned or "unknown")


# ---------------------------------------------------------------------------
# Complete 8-Table MySQL 8.0 / MariaDB DDL Specification
# ---------------------------------------------------------------------------

MYSQL_SCHEMA_DDL: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS articles (
        id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
        provider VARCHAR(16) NOT NULL COMMENT 'Store key: az, lv, ml, ph',
        identifier VARCHAR(2048) NOT NULL COMMENT 'Store-native product ID (ASIN, MLM, SKU, or legacy URL)',
        title TEXT NOT NULL,
        price DECIMAL(16, 2) NOT NULL DEFAULT 0.00,
        initial_price DECIMAL(16, 2) NOT NULL DEFAULT 0.00 COMMENT 'Price when first discovered',
        lowest_price DECIMAL(16, 2) NOT NULL DEFAULT 0.00 COMMENT 'All-time lowest price observed',
        lowest_price_at VARCHAR(64) DEFAULT NULL COMMENT 'Timestamp when lowest_price was observed',
        highest_price DECIMAL(16, 2) NOT NULL DEFAULT 0.00 COMMENT 'All-time highest price observed',
        highest_price_at VARCHAR(64) DEFAULT NULL COMMENT 'Timestamp when highest_price was observed',
        url TEXT NOT NULL,
        status VARCHAR(32) NOT NULL DEFAULT 'active' COMMENT 'Store-global status: active | on_hold | finished',
        hold_misses INT NOT NULL DEFAULT 0 COMMENT 'Store-global summary miss counter',
        created_at VARCHAR(64) NOT NULL COMMENT 'First seen timestamp (matches Article.datetime)',
        last_updated VARCHAR(64) DEFAULT NULL COMMENT 'Last price/title update timestamp',
        last_fetched_epoch DOUBLE NOT NULL DEFAULT 0.0 COMMENT 'Monotonic epoch guard against stale CDN pages',
        version BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT 'Optimistic concurrency version counter',
        PRIMARY KEY (id),
        UNIQUE KEY uk_articles_provider_identifier (provider, identifier(512)),
        KEY idx_articles_provider_status (provider, status),
        KEY idx_articles_last_updated (provider, last_updated)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS article_history (
        id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
        article_id BIGINT UNSIGNED NOT NULL,
        recorded_at VARCHAR(64) NOT NULL COMMENT 'Timestamp associated with the previous state',
        title TEXT DEFAULT NULL COMMENT 'Previous title if title changed',
        price DECIMAL(16, 2) DEFAULT NULL COMMENT 'Previous price if price changed',
        PRIMARY KEY (id),
        KEY idx_article_history_article_id (article_id, id),
        CONSTRAINT fk_article_history_article
            FOREIGN KEY (article_id) REFERENCES articles (id)
            ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS article_status_history (
        id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
        article_id BIGINT UNSIGNED NOT NULL,
        recorded_at VARCHAR(64) NOT NULL,
        status VARCHAR(32) NOT NULL COMMENT 'Lifecycle transition: active | finished',
        PRIMARY KEY (id),
        KEY idx_article_status_history_article_id (article_id, id),
        CONSTRAINT fk_article_status_history_article
            FOREIGN KEY (article_id) REFERENCES articles (id)
            ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS searches (
        id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
        provider VARCHAR(16) NOT NULL COMMENT 'Store key: az, lv, ml, ph',
        job_id VARCHAR(255) NOT NULL COMMENT 'Human-readable job_id from jobs.yaml',
        storage_path VARCHAR(255) NOT NULL COMMENT 'Normalized qualifier slug (maps to legacy JSON filename)',
        is_enabled TINYINT(1) NOT NULL DEFAULT 1 COMMENT '1 if active in jobs.yaml, 0 if archived/commented-out',
        is_first_run TINYINT(1) NOT NULL DEFAULT 1 COMMENT '1 until the search completes its first scrape cycle',
        query_text TEXT DEFAULT NULL COMMENT 'Search query string if query-based',
        resolved_url TEXT DEFAULT NULL COMMENT 'Target entry URL built by provider factory',
        filter_config JSON DEFAULT NULL COMMENT 'JSON object of seller, brand, page, category, state, talla',
        last_status VARCHAR(32) DEFAULT NULL COMMENT 'ok | incomplete | blocked',
        blocked_reason VARCHAR(128) DEFAULT NULL COMMENT 'Last anti-bot or HTTP error code if blocked',
        last_synced_at VARCHAR(64) DEFAULT NULL COMMENT 'Timestamp of last completed scrape cycle',
        PRIMARY KEY (id),
        UNIQUE KEY uk_searches_provider_job_id (provider, job_id),
        UNIQUE KEY uk_searches_storage_path (storage_path),
        KEY idx_searches_provider_enabled (provider, is_enabled)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS search_articles (
        search_id BIGINT UNSIGNED NOT NULL,
        article_id BIGINT UNSIGNED NOT NULL,
        status VARCHAR(32) NOT NULL DEFAULT 'active' COMMENT 'Per-search status: active | on_hold | finished',
        hold_misses INT NOT NULL DEFAULT 0 COMMENT 'Consecutive missed scrape cycles in this specific search',
        first_seen_at VARCHAR(64) NOT NULL,
        last_seen_at VARCHAR(64) NOT NULL,
        PRIMARY KEY (search_id, article_id),
        KEY idx_search_articles_article_status (article_id, status),
        KEY idx_search_articles_search_status (search_id, status),
        CONSTRAINT fk_search_articles_search
            FOREIGN KEY (search_id) REFERENCES searches (id)
            ON DELETE CASCADE,
        CONSTRAINT fk_search_articles_article
            FOREIGN KEY (article_id) REFERENCES articles (id)
            ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS notification_events (
        id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
        article_id BIGINT UNSIGNED NOT NULL,
        search_id BIGINT UNSIGNED DEFAULT NULL,
        event_type VARCHAR(32) NOT NULL COMMENT 'new_element | price_drop | is_updated',
        old_price DECIMAL(16, 2) DEFAULT NULL,
        new_price DECIMAL(16, 2) NOT NULL,
        percent_change DECIMAL(8, 2) DEFAULT NULL,
        observer_name VARCHAR(64) NOT NULL DEFAULT 'telegram',
        delivery_status VARCHAR(32) NOT NULL DEFAULT 'sent' COMMENT 'queued | sent | failed | skipped',
        error_message TEXT DEFAULT NULL,
        created_at VARCHAR(64) NOT NULL,
        PRIMARY KEY (id),
        KEY idx_notification_events_article (article_id, event_type, new_price),
        KEY idx_notification_events_created_at (created_at),
        CONSTRAINT fk_notification_events_article
            FOREIGN KEY (article_id) REFERENCES articles (id)
            ON DELETE CASCADE,
        CONSTRAINT fk_notification_events_search
            FOREIGN KEY (search_id) REFERENCES searches (id)
            ON DELETE SET NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS scrape_runs (
        id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
        search_id BIGINT UNSIGNED NOT NULL,
        provider VARCHAR(16) NOT NULL,
        started_at VARCHAR(64) NOT NULL,
        finished_at VARCHAR(64) NOT NULL,
        duration_s DOUBLE NOT NULL DEFAULT 0.0,
        pages_fetched INT NOT NULL DEFAULT 0,
        scraped_count INT NOT NULL DEFAULT 0,
        new_count INT NOT NULL DEFAULT 0,
        updated_count INT NOT NULL DEFAULT 0,
        missing_count INT NOT NULL DEFAULT 0,
        status VARCHAR(32) NOT NULL COMMENT 'ok | incomplete | blocked',
        error_reason VARCHAR(128) DEFAULT NULL,
        PRIMARY KEY (id),
        KEY idx_scrape_runs_search_started (search_id, started_at),
        KEY idx_scrape_runs_provider_status (provider, status),
        CONSTRAINT fk_scrape_runs_search
            FOREIGN KEY (search_id) REFERENCES searches (id)
            ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS provider_url_cache (
        provider VARCHAR(16) NOT NULL,
        cache_key VARCHAR(255) NOT NULL COMMENT 'e.g. query::page_name',
        resolved_segment TEXT NOT NULL,
        resolved_url TEXT NOT NULL,
        updated_at VARCHAR(64) NOT NULL,
        PRIMARY KEY (provider, cache_key)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
)

SQLITE_SCHEMA_DDL: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS articles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        provider TEXT NOT NULL,
        identifier TEXT NOT NULL,
        title TEXT NOT NULL,
        price REAL NOT NULL DEFAULT 0.0,
        initial_price REAL NOT NULL DEFAULT 0.0,
        lowest_price REAL NOT NULL DEFAULT 0.0,
        lowest_price_at TEXT DEFAULT NULL,
        highest_price REAL NOT NULL DEFAULT 0.0,
        highest_price_at TEXT DEFAULT NULL,
        url TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'active',
        hold_misses INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        last_updated TEXT DEFAULT NULL,
        last_fetched_epoch REAL NOT NULL DEFAULT 0.0,
        version INTEGER NOT NULL DEFAULT 1,
        UNIQUE (provider, identifier)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS article_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        article_id INTEGER NOT NULL,
        recorded_at TEXT NOT NULL,
        title TEXT DEFAULT NULL,
        price REAL DEFAULT NULL,
        FOREIGN KEY (article_id) REFERENCES articles (id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS article_status_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        article_id INTEGER NOT NULL,
        recorded_at TEXT NOT NULL,
        status TEXT NOT NULL,
        FOREIGN KEY (article_id) REFERENCES articles (id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS searches (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        provider TEXT NOT NULL,
        job_id TEXT NOT NULL,
        storage_path TEXT NOT NULL,
        is_enabled INTEGER NOT NULL DEFAULT 1,
        is_first_run INTEGER NOT NULL DEFAULT 1,
        query_text TEXT DEFAULT NULL,
        resolved_url TEXT DEFAULT NULL,
        filter_config TEXT DEFAULT NULL,
        last_status TEXT DEFAULT NULL,
        blocked_reason TEXT DEFAULT NULL,
        last_synced_at TEXT DEFAULT NULL,
        UNIQUE (provider, job_id),
        UNIQUE (storage_path)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS search_articles (
        search_id INTEGER NOT NULL,
        article_id INTEGER NOT NULL,
        status TEXT NOT NULL DEFAULT 'active',
        hold_misses INTEGER NOT NULL DEFAULT 0,
        first_seen_at TEXT NOT NULL,
        last_seen_at TEXT NOT NULL,
        PRIMARY KEY (search_id, article_id),
        FOREIGN KEY (search_id) REFERENCES searches (id) ON DELETE CASCADE,
        FOREIGN KEY (article_id) REFERENCES articles (id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS notification_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        article_id INTEGER NOT NULL,
        search_id INTEGER DEFAULT NULL,
        event_type TEXT NOT NULL,
        old_price REAL DEFAULT NULL,
        new_price REAL NOT NULL,
        percent_change REAL DEFAULT NULL,
        observer_name TEXT NOT NULL DEFAULT 'telegram',
        delivery_status TEXT NOT NULL DEFAULT 'sent',
        error_message TEXT DEFAULT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY (article_id) REFERENCES articles (id) ON DELETE CASCADE,
        FOREIGN KEY (search_id) REFERENCES searches (id) ON DELETE SET NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS scrape_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        search_id INTEGER NOT NULL,
        provider TEXT NOT NULL,
        started_at TEXT NOT NULL,
        finished_at TEXT NOT NULL,
        duration_s REAL NOT NULL DEFAULT 0.0,
        pages_fetched INTEGER NOT NULL DEFAULT 0,
        scraped_count INTEGER NOT NULL DEFAULT 0,
        new_count INTEGER NOT NULL DEFAULT 0,
        updated_count INTEGER NOT NULL DEFAULT 0,
        missing_count INTEGER NOT NULL DEFAULT 0,
        status TEXT NOT NULL,
        error_reason TEXT DEFAULT NULL,
        FOREIGN KEY (search_id) REFERENCES searches (id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS provider_url_cache (
        provider TEXT NOT NULL,
        cache_key TEXT NOT NULL,
        resolved_segment TEXT NOT NULL,
        resolved_url TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (provider, cache_key)
    )
    """,
)


# ---------------------------------------------------------------------------
# Data Transfer Objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DatabaseConfig:
    """Connection parameters for the persistence layer."""

    host: str = "127.0.0.1"
    port: int = 3306
    user: str = "mlscraper"
    password: str = "mlscraper"
    database: str = "mlscraper"
    backend: str = "auto"

    @staticmethod
    def from_env() -> DatabaseConfig:
        """Load database configuration from environment variables."""
        return DatabaseConfig(
            host=os.environ.get("DB_HOST", "127.0.0.1"),
            port=int(os.environ.get("DB_PORT", "3306")),
            user=os.environ.get("DB_USER", "mlscraper"),
            password=os.environ.get("DB_PASSWORD", "mlscraper"),
            database=os.environ.get("DB_NAME", "mlscraper"),
            backend=os.environ.get("PERSISTENCE_BACKEND", "auto").strip().lower(),
        )


@dataclass
class SearchRecord:
    """Row representation for the ``searches`` table."""

    id: int
    provider: str
    job_id: str
    storage_path: str
    is_enabled: bool = True
    is_first_run: bool = True
    query_text: Optional[str] = None
    resolved_url: Optional[str] = None
    filter_config: Optional[dict[str, Any]] = None
    last_status: Optional[str] = None
    blocked_reason: Optional[str] = None
    last_synced_at: Optional[str] = None


@dataclass
class SearchArticleState:
    """Per-search article membership state stored in ``search_articles``."""

    search_id: int
    article_id: int
    identifier: str
    status: str = "active"
    hold_misses: int = 0
    first_seen_at: str = ""
    last_seen_at: str = ""
    is_search_enabled: bool = True


@dataclass
class ScrapeRunRecord:
    """Telemetry record for a single search scrape cycle in ``scrape_runs``."""

    search_id: int
    provider: str
    started_at: str
    finished_at: str
    duration_s: float
    pages_fetched: int
    scraped_count: int
    new_count: int
    updated_count: int
    missing_count: int
    status: str
    error_reason: Optional[str] = None


@dataclass
class NotificationEventRecord:
    """Audit record for a notification event in ``notification_events``."""

    article_id: int
    search_id: Optional[int]
    event_type: str
    old_price: Optional[float]
    new_price: float
    percent_change: Optional[float]
    observer_name: str = "telegram"
    delivery_status: str = "sent"
    error_message: Optional[str] = None
    created_at: str = field(default_factory=lambda: str(datetime_lib.now()))


@dataclass
class StoreSnapshot:
    """Bulk-hydrated store state loaded from the database on startup."""

    provider: str
    articles: list[dict[str, Any]] = field(default_factory=list)
    history_by_article_id: dict[int, list[dict[str, Any]]] = field(default_factory=dict)
    status_history_by_article_id: dict[int, list[dict[str, Any]]] = field(default_factory=dict)
    searches_by_storage_path: dict[str, SearchRecord] = field(default_factory=dict)
    search_articles_by_search_id: dict[int, list[SearchArticleState]] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Persistence Backend Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class PersistenceBackend(Protocol):
    """Protocol implemented by relational persistence backends (MySQL and SQLite)."""

    def ensure_schema(self) -> None:
        """Create all 8 relational tables and indexes if they do not exist."""
        ...

    def upsert_search(
        self,
        *,
        provider: str,
        job_id: str,
        storage_path: str,
        is_enabled: bool = True,
        query_text: str | None = None,
        resolved_url: str | None = None,
        filter_config: dict[str, Any] | None = None,
    ) -> SearchRecord:
        """Insert or update a search definition and return its :class:`SearchRecord`."""
        ...

    def mark_unlisted_searches_disabled(
        self,
        enabled_storage_paths: set[str],
        *,
        provider: str | None = None,
    ) -> None:
        """Set ``is_enabled = 0`` for searches not present in ``enabled_storage_paths``."""
        ...

    def load_store_snapshot(self, provider: str) -> StoreSnapshot:
        """Bulk-load all canonical articles, histories, searches, and memberships for a store."""
        ...

    def insert_or_get_article(
        self,
        *,
        provider: str,
        identifier: str,
        title: str,
        price: float,
        initial_price: float,
        lowest_price: float,
        lowest_price_at: str | None,
        highest_price: float,
        highest_price_at: str | None,
        url: str,
        status: str,
        hold_misses: int,
        created_at: str,
        last_updated: str | None,
        last_fetched_epoch: float,
        search_id: int | None = None,
        search_status: str = "active",
        search_hold_misses: int = 0,
        record_initial_status: bool = True,
    ) -> tuple[int, bool, dict[str, Any] | None]:
        """Atomically insert a new store article or return the existing row."""
        ...

    def cas_update_article(
        self,
        *,
        article_id: int,
        new_title: str,
        new_price: float,
        lowest_price: float,
        lowest_price_at: str | None,
        highest_price: float,
        highest_price_at: str | None,
        url: str,
        status: str,
        hold_misses: int,
        last_updated: str,
        last_fetched_epoch: float,
        history_entry: dict[str, Any] | None = None,
        status_history_entry: dict[str, Any] | None = None,
    ) -> tuple[bool, dict[str, Any] | None]:
        """Atomically update an article only when price or title actually differs in the DB."""
        ...

    def update_article_status(
        self,
        *,
        article_id: int,
        status: str,
        hold_misses: int,
        last_fetched_epoch: float | None = None,
        status_history_entry: dict[str, Any] | None = None,
    ) -> None:
        """Persist a store-global status and hold_misses update for an article."""
        ...

    def flush_search_cycle(
        self,
        *,
        search_id: int,
        is_first_run: bool,
        last_status: str,
        blocked_reason: str | None,
        last_synced_at: str,
        memberships: Sequence[SearchArticleState],
        global_status_updates: Sequence[tuple[int, str, int, dict[str, Any] | None]] = (),
        scrape_run: ScrapeRunRecord | None = None,
    ) -> None:
        """Batch-commit search memberships, global status updates, and cycle telemetry."""
        ...

    def record_notification_event(self, event: NotificationEventRecord) -> int:
        """Insert a notification event audit row and return its ID."""
        ...

    def has_notification_event(
        self,
        *,
        article_id: int,
        event_type: str,
        new_price: float,
        observer_name: str = "telegram",
    ) -> bool:
        """Return ``True`` if a sent notification already exists for the same transition."""
        ...

    def get_cached_url(self, provider: str, cache_key: str) -> tuple[str, str] | None:
        """Return ``(resolved_segment, resolved_url)`` from ``provider_url_cache`` if present."""
        ...

    def set_cached_url(
        self,
        *,
        provider: str,
        cache_key: str,
        resolved_segment: str,
        resolved_url: str,
        updated_at: str | None = None,
    ) -> None:
        """Upsert a resolved URL segment into ``provider_url_cache``."""
        ...


# ---------------------------------------------------------------------------
# Shared SQL Helpers & Base Relational Backend
# ---------------------------------------------------------------------------


def _json_dumps_compact(data: dict[str, Any] | None) -> str | None:
    if not data:
        return None
    return json.dumps(data, ensure_ascii=False, sort_keys=True)


def _json_loads_dict(raw: Any) -> dict[str, Any] | None:
    if not raw:
        return None
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", errors="replace")
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else None
        except ValueError:
            return None
    return None


class MySQLPersistenceBackend:
    """MySQL / MariaDB implementation of :class:`PersistenceBackend` using PyMySQL."""

    def __init__(self, config: DatabaseConfig | None = None) -> None:
        self.config = config or DatabaseConfig.from_env()
        self._schema_ensured = False
        self._lock = threading.RLock()

    def _connect(self) -> pymysql.connections.Connection:
        return pymysql.connect(
            host=self.config.host,
            port=self.config.port,
            user=self.config.user,
            password=self.config.password,
            database=self.config.database,
            charset="utf8mb4",
            cursorclass=DictCursor,
            autocommit=False,
            connect_timeout=5,
            read_timeout=30,
            write_timeout=30,
        )

    @contextmanager
    def _transaction(self) -> Iterator[Any]:
        conn = self._connect()
        try:
            with conn.cursor() as cursor:
                yield cursor
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def ping(self) -> bool:
        """Return ``True`` when the MySQL server is reachable."""
        try:
            conn = self._connect()
            conn.close()
            return True
        except Exception:
            return False

    def ensure_schema(self) -> None:
        """Create all 8 relational tables if they do not exist and upgrade column widths if needed."""
        with self._lock:
            if self._schema_ensured:
                return
            with self._transaction() as cursor:
                for ddl in MYSQL_SCHEMA_DDL:
                    cursor.execute(ddl)
                # Ensure legacy VARCHAR(128) identifier column is widened to VARCHAR(2048)
                cursor.execute("""
                    SELECT CHARACTER_MAXIMUM_LENGTH
                    FROM information_schema.COLUMNS
                    WHERE TABLE_SCHEMA = DATABASE()
                      AND TABLE_NAME = 'articles'
                      AND COLUMN_NAME = 'identifier'
                    """)
                col_info = cursor.fetchone()
                if (
                    isinstance(col_info, dict)
                    and col_info.get("CHARACTER_MAXIMUM_LENGTH") is not None
                    and int(col_info["CHARACTER_MAXIMUM_LENGTH"]) < 2048
                ):
                    cursor.execute(
                        "ALTER TABLE articles DROP INDEX uk_articles_provider_identifier"
                    )
                    cursor.execute("""
                        ALTER TABLE articles
                        MODIFY COLUMN identifier VARCHAR(2048) NOT NULL,
                        MODIFY COLUMN price DECIMAL(16, 2) NOT NULL DEFAULT 0.00,
                        MODIFY COLUMN initial_price DECIMAL(16, 2) NOT NULL DEFAULT 0.00,
                        MODIFY COLUMN lowest_price DECIMAL(16, 2) NOT NULL DEFAULT 0.00,
                        MODIFY COLUMN highest_price DECIMAL(16, 2) NOT NULL DEFAULT 0.00,
                        ADD UNIQUE KEY uk_articles_provider_identifier (provider, identifier(512))
                        """)
                    cursor.execute(
                        "ALTER TABLE article_history MODIFY COLUMN price DECIMAL(16, 2) DEFAULT NULL"
                    )
            self._schema_ensured = True

    def upsert_search(
        self,
        *,
        provider: str,
        job_id: str,
        storage_path: str,
        is_enabled: bool = True,
        query_text: str | None = None,
        resolved_url: str | None = None,
        filter_config: dict[str, Any] | None = None,
    ) -> SearchRecord:
        self.ensure_schema()
        provider_key = normalize_provider_key(provider)
        filter_json = _json_dumps_compact(filter_config)
        enabled_int = 1 if is_enabled else 0

        with self._transaction() as cursor:
            cursor.execute(
                """
                INSERT INTO searches (
                    provider, job_id, storage_path, is_enabled, is_first_run,
                    query_text, resolved_url, filter_config
                )
                VALUES (%s, %s, %s, %s, 1, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    id = LAST_INSERT_ID(id),
                    provider = VALUES(provider),
                    job_id = VALUES(job_id),
                    storage_path = VALUES(storage_path),
                    is_enabled = VALUES(is_enabled),
                    query_text = COALESCE(VALUES(query_text), query_text),
                    resolved_url = COALESCE(VALUES(resolved_url), resolved_url),
                    filter_config = COALESCE(VALUES(filter_config), filter_config)
                """,
                (
                    provider_key,
                    job_id,
                    storage_path,
                    enabled_int,
                    query_text,
                    resolved_url,
                    filter_json,
                ),
            )
            cursor.execute(
                "SELECT * FROM searches WHERE storage_path = %s OR (provider = %s AND job_id = %s) LIMIT 1",
                (storage_path, provider_key, job_id),
            )
            row = cursor.fetchone()
            assert row is not None
            return self._row_to_search_record(row)

    def mark_unlisted_searches_disabled(
        self,
        enabled_storage_paths: set[str],
        *,
        provider: str | None = None,
    ) -> None:
        self.ensure_schema()
        with self._transaction() as cursor:
            if not enabled_storage_paths:
                if provider:
                    cursor.execute(
                        "UPDATE searches SET is_enabled = 0 WHERE provider = %s",
                        (normalize_provider_key(provider),),
                    )
                else:
                    cursor.execute("UPDATE searches SET is_enabled = 0")
                return

            placeholders = ", ".join(["%s"] * len(enabled_storage_paths))
            params: list[Any] = list(enabled_storage_paths)
            if provider:
                params.append(normalize_provider_key(provider))
                cursor.execute(
                    f"UPDATE searches SET is_enabled = 0 WHERE storage_path NOT IN ({placeholders}) AND provider = %s",
                    params,
                )
            else:
                cursor.execute(
                    f"UPDATE searches SET is_enabled = 0 WHERE storage_path NOT IN ({placeholders})",
                    params,
                )

    def load_store_snapshot(self, provider: str) -> StoreSnapshot:
        self.ensure_schema()
        provider_key = normalize_provider_key(provider)
        snapshot = StoreSnapshot(provider=provider_key)

        with self._transaction() as cursor:
            cursor.execute(
                "SELECT * FROM articles WHERE provider = %s ORDER BY id ASC",
                (provider_key,),
            )
            articles = list(cursor.fetchall())
            snapshot.articles = articles
            article_ids = [int(row["id"]) for row in articles]
            identifier_by_id = {int(row["id"]): str(row["identifier"]) for row in articles}

            if article_ids:
                id_placeholders = ", ".join(["%s"] * len(article_ids))
                cursor.execute(
                    f"""
                    SELECT * FROM article_history
                    WHERE article_id IN ({id_placeholders})
                    ORDER BY id DESC
                    """,
                    article_ids,
                )
                for h_row in cursor.fetchall():
                    aid = int(h_row["article_id"])
                    bucket = snapshot.history_by_article_id.setdefault(aid, [])
                    if len(bucket) < MAX_DB_HISTORY:
                        bucket.append(h_row)

                cursor.execute(
                    f"""
                    SELECT * FROM article_status_history
                    WHERE article_id IN ({id_placeholders})
                    ORDER BY id DESC
                    """,
                    article_ids,
                )
                for sh_row in cursor.fetchall():
                    aid = int(sh_row["article_id"])
                    bucket = snapshot.status_history_by_article_id.setdefault(aid, [])
                    if len(bucket) < MAX_DB_HISTORY:
                        bucket.append(sh_row)

            cursor.execute(
                "SELECT * FROM searches WHERE provider = %s",
                (provider_key,),
            )
            search_rows = list(cursor.fetchall())
            enabled_by_search_id: dict[int, bool] = {}
            for s_row in search_rows:
                record = self._row_to_search_record(s_row)
                snapshot.searches_by_storage_path[record.storage_path] = record
                enabled_by_search_id[record.id] = record.is_enabled

            if search_rows:
                s_ids = [int(s["id"]) for s in search_rows]
                s_placeholders = ", ".join(["%s"] * len(s_ids))
                cursor.execute(
                    f"SELECT * FROM search_articles WHERE search_id IN ({s_placeholders})",
                    s_ids,
                )
                for sa_row in cursor.fetchall():
                    aid = int(sa_row["article_id"])
                    sid = int(sa_row["search_id"])
                    ident = identifier_by_id.get(aid)
                    if not ident:
                        continue
                    state = SearchArticleState(
                        search_id=sid,
                        article_id=aid,
                        identifier=ident,
                        status=str(sa_row["status"]),
                        hold_misses=int(sa_row["hold_misses"] or 0),
                        first_seen_at=str(sa_row["first_seen_at"]),
                        last_seen_at=str(sa_row["last_seen_at"]),
                        is_search_enabled=enabled_by_search_id.get(sid, True),
                    )
                    snapshot.search_articles_by_search_id.setdefault(sid, []).append(state)

        return snapshot

    def insert_or_get_article(
        self,
        *,
        provider: str,
        identifier: str,
        title: str,
        price: float,
        initial_price: float,
        lowest_price: float,
        lowest_price_at: str | None,
        highest_price: float,
        highest_price_at: str | None,
        url: str,
        status: str,
        hold_misses: int,
        created_at: str,
        last_updated: str | None,
        last_fetched_epoch: float,
        search_id: int | None = None,
        search_status: str = "active",
        search_hold_misses: int = 0,
        record_initial_status: bool = True,
    ) -> tuple[int, bool, dict[str, Any] | None]:
        self.ensure_schema()
        provider_key = normalize_provider_key(provider)
        with self._transaction() as cursor:
            cursor.execute(
                "SELECT * FROM articles WHERE provider = %s AND identifier = %s LIMIT 1",
                (provider_key, identifier),
            )
            existing = cursor.fetchone()
            if existing is not None:
                article_id = int(existing["id"])
                if search_id is not None:
                    self._upsert_search_article_cursor(
                        cursor,
                        search_id=search_id,
                        article_id=article_id,
                        status=search_status,
                        hold_misses=search_hold_misses,
                        first_seen_at=created_at,
                        last_seen_at=last_updated or created_at,
                    )
                return article_id, False, dict(existing)

            cursor.execute(
                """
                INSERT INTO articles (
                    provider, identifier, title, price,
                    initial_price, lowest_price, lowest_price_at,
                    highest_price, highest_price_at, url,
                    status, hold_misses, created_at, last_updated,
                    last_fetched_epoch, version
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 1)
                """,
                (
                    provider_key,
                    identifier,
                    title,
                    price,
                    initial_price,
                    lowest_price,
                    lowest_price_at,
                    highest_price,
                    highest_price_at,
                    url or "",
                    status,
                    hold_misses,
                    created_at,
                    last_updated,
                    last_fetched_epoch,
                ),
            )
            article_id = int(cursor.lastrowid)
            if record_initial_status and status in ("active", "finished"):
                cursor.execute(
                    """
                    INSERT INTO article_status_history (article_id, recorded_at, status)
                    VALUES (%s, %s, %s)
                    """,
                    (article_id, created_at, status),
                )
            if search_id is not None:
                self._upsert_search_article_cursor(
                    cursor,
                    search_id=search_id,
                    article_id=article_id,
                    status=search_status,
                    hold_misses=search_hold_misses,
                    first_seen_at=created_at,
                    last_seen_at=last_updated or created_at,
                )
            return article_id, True, None

    def cas_update_article(
        self,
        *,
        article_id: int,
        new_title: str,
        new_price: float,
        lowest_price: float,
        lowest_price_at: str | None,
        highest_price: float,
        highest_price_at: str | None,
        url: str,
        status: str,
        hold_misses: int,
        last_updated: str,
        last_fetched_epoch: float,
        history_entry: dict[str, Any] | None = None,
        status_history_entry: dict[str, Any] | None = None,
    ) -> tuple[bool, dict[str, Any] | None]:
        self.ensure_schema()
        with self._transaction() as cursor:
            cursor.execute(
                """
                UPDATE articles
                SET title = %s,
                    price = %s,
                    lowest_price = %s,
                    lowest_price_at = %s,
                    highest_price = %s,
                    highest_price_at = %s,
                    url = COALESCE(NULLIF(%s, ''), url),
                    status = %s,
                    hold_misses = %s,
                    last_updated = %s,
                    last_fetched_epoch = GREATEST(last_fetched_epoch, %s),
                    version = version + 1
                WHERE id = %s
                  AND (price != %s OR title != %s)
                  AND last_fetched_epoch <= %s
                """,
                (
                    new_title,
                    new_price,
                    lowest_price,
                    lowest_price_at,
                    highest_price,
                    highest_price_at,
                    url or "",
                    status,
                    hold_misses,
                    last_updated,
                    last_fetched_epoch,
                    article_id,
                    new_price,
                    new_title,
                    last_fetched_epoch,
                ),
            )
            if cursor.rowcount == 0:
                cursor.execute("SELECT * FROM articles WHERE id = %s", (article_id,))
                current = cursor.fetchone()
                return False, dict(current) if current else None

            if history_entry is not None:
                cursor.execute(
                    """
                    INSERT INTO article_history (article_id, recorded_at, title, price)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (
                        article_id,
                        str(history_entry["datetime"]),
                        history_entry.get("title"),
                        history_entry.get("price"),
                    ),
                )

            if status_history_entry is not None:
                cursor.execute(
                    """
                    INSERT INTO article_status_history (article_id, recorded_at, status)
                    VALUES (%s, %s, %s)
                    """,
                    (
                        article_id,
                        str(status_history_entry["datetime"]),
                        str(status_history_entry["status"]),
                    ),
                )

            return True, None

    def update_article_status(
        self,
        *,
        article_id: int,
        status: str,
        hold_misses: int,
        last_fetched_epoch: float | None = None,
        status_history_entry: dict[str, Any] | None = None,
    ) -> None:
        self.ensure_schema()
        with self._transaction() as cursor:
            if last_fetched_epoch is not None:
                cursor.execute(
                    """
                    UPDATE articles
                    SET status = %s,
                        hold_misses = %s,
                        last_fetched_epoch = GREATEST(last_fetched_epoch, %s)
                    WHERE id = %s
                    """,
                    (status, hold_misses, last_fetched_epoch, article_id),
                )
            else:
                cursor.execute(
                    """
                    UPDATE articles
                    SET status = %s,
                        hold_misses = %s
                    WHERE id = %s
                    """,
                    (status, hold_misses, article_id),
                )

            if status_history_entry is not None:
                cursor.execute(
                    """
                    INSERT INTO article_status_history (article_id, recorded_at, status)
                    VALUES (%s, %s, %s)
                    """,
                    (
                        article_id,
                        str(status_history_entry["datetime"]),
                        str(status_history_entry["status"]),
                    ),
                )

    def flush_search_cycle(
        self,
        *,
        search_id: int,
        is_first_run: bool,
        last_status: str,
        blocked_reason: str | None,
        last_synced_at: str,
        memberships: Sequence[SearchArticleState],
        global_status_updates: Sequence[tuple[int, str, int, dict[str, Any] | None]] = (),
        scrape_run: ScrapeRunRecord | None = None,
    ) -> None:
        self.ensure_schema()
        with self._transaction() as cursor:
            if memberships:
                cursor.executemany(
                    """
                    INSERT INTO search_articles (
                        search_id, article_id, status, hold_misses, first_seen_at, last_seen_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        status = VALUES(status),
                        hold_misses = VALUES(hold_misses),
                        last_seen_at = VALUES(last_seen_at)
                    """,
                    [
                        (
                            search_id,
                            item.article_id,
                            item.status,
                            item.hold_misses,
                            item.first_seen_at,
                            item.last_seen_at,
                        )
                        for item in memberships
                    ],
                )

            for article_id, status, hold_misses, status_entry in global_status_updates:
                cursor.execute(
                    "UPDATE articles SET status = %s, hold_misses = %s WHERE id = %s",
                    (status, hold_misses, article_id),
                )
                if status_entry is not None:
                    cursor.execute(
                        """
                        INSERT INTO article_status_history (article_id, recorded_at, status)
                        VALUES (%s, %s, %s)
                        """,
                        (
                            article_id,
                            str(status_entry["datetime"]),
                            str(status_entry["status"]),
                        ),
                    )

            cursor.execute(
                """
                UPDATE searches
                SET is_first_run = %s,
                    last_status = %s,
                    blocked_reason = %s,
                    last_synced_at = %s
                WHERE id = %s
                """,
                (1 if is_first_run else 0, last_status, blocked_reason, last_synced_at, search_id),
            )

            if scrape_run is not None:
                cursor.execute(
                    """
                    INSERT INTO scrape_runs (
                        search_id, provider, started_at, finished_at, duration_s,
                        pages_fetched, scraped_count, new_count, updated_count,
                        missing_count, status, error_reason
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        scrape_run.search_id,
                        normalize_provider_key(scrape_run.provider),
                        scrape_run.started_at,
                        scrape_run.finished_at,
                        scrape_run.duration_s,
                        scrape_run.pages_fetched,
                        scrape_run.scraped_count,
                        scrape_run.new_count,
                        scrape_run.updated_count,
                        scrape_run.missing_count,
                        scrape_run.status,
                        scrape_run.error_reason,
                    ),
                )

    def record_notification_event(self, event: NotificationEventRecord) -> int:
        self.ensure_schema()
        with self._transaction() as cursor:
            cursor.execute(
                """
                INSERT INTO notification_events (
                    article_id, search_id, event_type, old_price, new_price,
                    percent_change, observer_name, delivery_status, error_message, created_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    event.article_id,
                    event.search_id,
                    event.event_type,
                    event.old_price,
                    event.new_price,
                    event.percent_change,
                    event.observer_name,
                    event.delivery_status,
                    event.error_message,
                    event.created_at,
                ),
            )
            return int(cursor.lastrowid)

    def has_notification_event(
        self,
        *,
        article_id: int,
        event_type: str,
        new_price: float,
        observer_name: str = "telegram",
    ) -> bool:
        self.ensure_schema()
        with self._transaction() as cursor:
            cursor.execute(
                """
                SELECT id FROM notification_events
                WHERE article_id = %s
                  AND event_type = %s
                  AND ABS(new_price - %s) < 0.005
                  AND observer_name = %s
                  AND delivery_status = 'sent'
                LIMIT 1
                """,
                (article_id, event_type, new_price, observer_name),
            )
            return cursor.fetchone() is not None

    def get_cached_url(self, provider: str, cache_key: str) -> tuple[str, str] | None:
        self.ensure_schema()
        provider_key = normalize_provider_key(provider)
        with self._transaction() as cursor:
            cursor.execute(
                """
                SELECT resolved_segment, resolved_url
                FROM provider_url_cache
                WHERE provider = %s AND cache_key = %s
                LIMIT 1
                """,
                (provider_key, cache_key),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return str(row["resolved_segment"]), str(row["resolved_url"])

    def set_cached_url(
        self,
        *,
        provider: str,
        cache_key: str,
        resolved_segment: str,
        resolved_url: str,
        updated_at: str | None = None,
    ) -> None:
        self.ensure_schema()
        provider_key = normalize_provider_key(provider)
        ts = updated_at or str(datetime_lib.now())
        with self._transaction() as cursor:
            cursor.execute(
                """
                INSERT INTO provider_url_cache (
                    provider, cache_key, resolved_segment, resolved_url, updated_at
                )
                VALUES (%s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    resolved_segment = VALUES(resolved_segment),
                    resolved_url = VALUES(resolved_url),
                    updated_at = VALUES(updated_at)
                """,
                (provider_key, cache_key, resolved_segment, resolved_url, ts),
            )

    @staticmethod
    def _upsert_search_article_cursor(
        cursor: Any,
        *,
        search_id: int,
        article_id: int,
        status: str,
        hold_misses: int,
        first_seen_at: str,
        last_seen_at: str,
    ) -> None:
        cursor.execute(
            """
            INSERT INTO search_articles (
                search_id, article_id, status, hold_misses, first_seen_at, last_seen_at
            )
            VALUES (%s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                status = VALUES(status),
                hold_misses = VALUES(hold_misses),
                last_seen_at = VALUES(last_seen_at)
            """,
            (search_id, article_id, status, hold_misses, first_seen_at, last_seen_at),
        )

    @staticmethod
    def _row_to_search_record(row: dict[str, Any]) -> SearchRecord:
        return SearchRecord(
            id=int(row["id"]),
            provider=str(row["provider"]),
            job_id=str(row["job_id"]),
            storage_path=str(row["storage_path"]),
            is_enabled=bool(row.get("is_enabled", 1)),
            is_first_run=bool(row.get("is_first_run", 1)),
            query_text=row.get("query_text"),
            resolved_url=row.get("resolved_url"),
            filter_config=_json_loads_dict(row.get("filter_config")),
            last_status=row.get("last_status"),
            blocked_reason=row.get("blocked_reason"),
            last_synced_at=row.get("last_synced_at"),
        )


class SQLitePersistenceBackend:
    """Relational SQLite implementation of :class:`PersistenceBackend`.

    Mirrors the exact 8-table schema and atomic Compare-And-Swap semantics of
    :class:`MySQLPersistenceBackend` for deterministic in-memory or file-backed
    testing and local environments where a MySQL daemon is not running.
    """

    def __init__(self, database_path: str | Path = ":memory:") -> None:
        self.database_path = str(database_path)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.database_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._schema_ensured = False

    def close(self) -> None:
        """Close the underlying SQLite connection."""
        with self._lock:
            self._conn.close()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Cursor]:
        with self._lock:
            cursor = self._conn.cursor()
            try:
                yield cursor
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise
            finally:
                cursor.close()

    def ensure_schema(self) -> None:
        with self._lock:
            if self._schema_ensured:
                return
            with self._transaction() as cursor:
                for ddl in SQLITE_SCHEMA_DDL:
                    cursor.execute(ddl)
            self._schema_ensured = True

    def upsert_search(
        self,
        *,
        provider: str,
        job_id: str,
        storage_path: str,
        is_enabled: bool = True,
        query_text: str | None = None,
        resolved_url: str | None = None,
        filter_config: dict[str, Any] | None = None,
    ) -> SearchRecord:
        self.ensure_schema()
        provider_key = normalize_provider_key(provider)
        filter_json = _json_dumps_compact(filter_config)
        enabled_int = 1 if is_enabled else 0

        with self._transaction() as cursor:
            cursor.execute(
                """
                SELECT * FROM searches
                WHERE storage_path = ? OR (provider = ? AND job_id = ?)
                LIMIT 1
                """,
                (storage_path, provider_key, job_id),
            )
            existing = cursor.fetchone()
            if existing is None:
                cursor.execute(
                    """
                    INSERT INTO searches (
                        provider, job_id, storage_path, is_enabled, is_first_run,
                        query_text, resolved_url, filter_config
                    )
                    VALUES (?, ?, ?, ?, 1, ?, ?, ?)
                    """,
                    (
                        provider_key,
                        job_id,
                        storage_path,
                        enabled_int,
                        query_text,
                        resolved_url,
                        filter_json,
                    ),
                )
            else:
                cursor.execute(
                    """
                    UPDATE searches
                    SET provider = ?,
                        job_id = ?,
                        storage_path = ?,
                        is_enabled = ?,
                        query_text = COALESCE(?, query_text),
                        resolved_url = COALESCE(?, resolved_url),
                        filter_config = COALESCE(?, filter_config)
                    WHERE id = ?
                    """,
                    (
                        provider_key,
                        job_id,
                        storage_path,
                        enabled_int,
                        query_text,
                        resolved_url,
                        filter_json,
                        int(existing["id"]),
                    ),
                )

            cursor.execute(
                """
                SELECT * FROM searches
                WHERE storage_path = ? OR (provider = ? AND job_id = ?)
                LIMIT 1
                """,
                (storage_path, provider_key, job_id),
            )
            row = cursor.fetchone()
            assert row is not None
            return MySQLPersistenceBackend._row_to_search_record(dict(row))

    def mark_unlisted_searches_disabled(
        self,
        enabled_storage_paths: set[str],
        *,
        provider: str | None = None,
    ) -> None:
        self.ensure_schema()
        with self._transaction() as cursor:
            if not enabled_storage_paths:
                if provider:
                    cursor.execute(
                        "UPDATE searches SET is_enabled = 0 WHERE provider = ?",
                        (normalize_provider_key(provider),),
                    )
                else:
                    cursor.execute("UPDATE searches SET is_enabled = 0")
                return

            placeholders = ", ".join(["?"] * len(enabled_storage_paths))
            params: list[Any] = list(enabled_storage_paths)
            if provider:
                params.append(normalize_provider_key(provider))
                cursor.execute(
                    f"UPDATE searches SET is_enabled = 0 WHERE storage_path NOT IN ({placeholders}) AND provider = ?",
                    params,
                )
            else:
                cursor.execute(
                    f"UPDATE searches SET is_enabled = 0 WHERE storage_path NOT IN ({placeholders})",
                    params,
                )

    def load_store_snapshot(self, provider: str) -> StoreSnapshot:
        self.ensure_schema()
        provider_key = normalize_provider_key(provider)
        snapshot = StoreSnapshot(provider=provider_key)

        with self._transaction() as cursor:
            cursor.execute(
                "SELECT * FROM articles WHERE provider = ? ORDER BY id ASC",
                (provider_key,),
            )
            articles = [dict(r) for r in cursor.fetchall()]
            snapshot.articles = articles
            article_ids = [int(row["id"]) for row in articles]
            identifier_by_id = {int(row["id"]): str(row["identifier"]) for row in articles}

            if article_ids:
                id_placeholders = ", ".join(["?"] * len(article_ids))
                cursor.execute(
                    f"""
                    SELECT * FROM article_history
                    WHERE article_id IN ({id_placeholders})
                    ORDER BY id DESC
                    """,
                    article_ids,
                )
                for h_row in cursor.fetchall():
                    d_row = dict(h_row)
                    aid = int(d_row["article_id"])
                    bucket = snapshot.history_by_article_id.setdefault(aid, [])
                    if len(bucket) < MAX_DB_HISTORY:
                        bucket.append(d_row)

                cursor.execute(
                    f"""
                    SELECT * FROM article_status_history
                    WHERE article_id IN ({id_placeholders})
                    ORDER BY id DESC
                    """,
                    article_ids,
                )
                for sh_row in cursor.fetchall():
                    d_row = dict(sh_row)
                    aid = int(d_row["article_id"])
                    bucket = snapshot.status_history_by_article_id.setdefault(aid, [])
                    if len(bucket) < MAX_DB_HISTORY:
                        bucket.append(d_row)

            cursor.execute(
                "SELECT * FROM searches WHERE provider = ?",
                (provider_key,),
            )
            search_rows = [dict(r) for r in cursor.fetchall()]
            enabled_by_search_id: dict[int, bool] = {}
            for s_row in search_rows:
                record = MySQLPersistenceBackend._row_to_search_record(s_row)
                snapshot.searches_by_storage_path[record.storage_path] = record
                enabled_by_search_id[record.id] = record.is_enabled

            if search_rows:
                s_ids = [int(s["id"]) for s in search_rows]
                s_placeholders = ", ".join(["?"] * len(s_ids))
                cursor.execute(
                    f"SELECT * FROM search_articles WHERE search_id IN ({s_placeholders})",
                    s_ids,
                )
                for sa_row in cursor.fetchall():
                    d_row = dict(sa_row)
                    aid = int(d_row["article_id"])
                    sid = int(d_row["search_id"])
                    ident = identifier_by_id.get(aid)
                    if not ident:
                        continue
                    state = SearchArticleState(
                        search_id=sid,
                        article_id=aid,
                        identifier=ident,
                        status=str(d_row["status"]),
                        hold_misses=int(d_row["hold_misses"] or 0),
                        first_seen_at=str(d_row["first_seen_at"]),
                        last_seen_at=str(d_row["last_seen_at"]),
                        is_search_enabled=enabled_by_search_id.get(sid, True),
                    )
                    snapshot.search_articles_by_search_id.setdefault(sid, []).append(state)

        return snapshot

    def insert_or_get_article(
        self,
        *,
        provider: str,
        identifier: str,
        title: str,
        price: float,
        initial_price: float,
        lowest_price: float,
        lowest_price_at: str | None,
        highest_price: float,
        highest_price_at: str | None,
        url: str,
        status: str,
        hold_misses: int,
        created_at: str,
        last_updated: str | None,
        last_fetched_epoch: float,
        search_id: int | None = None,
        search_status: str = "active",
        search_hold_misses: int = 0,
        record_initial_status: bool = True,
    ) -> tuple[int, bool, dict[str, Any] | None]:
        self.ensure_schema()
        provider_key = normalize_provider_key(provider)
        with self._transaction() as cursor:
            cursor.execute(
                "SELECT * FROM articles WHERE provider = ? AND identifier = ? LIMIT 1",
                (provider_key, identifier),
            )
            existing = cursor.fetchone()
            if existing is not None:
                d_existing = dict(existing)
                article_id = int(d_existing["id"])
                if search_id is not None:
                    self._upsert_search_article_cursor(
                        cursor,
                        search_id=search_id,
                        article_id=article_id,
                        status=search_status,
                        hold_misses=search_hold_misses,
                        first_seen_at=created_at,
                        last_seen_at=last_updated or created_at,
                    )
                return article_id, False, d_existing

            cursor.execute(
                """
                INSERT INTO articles (
                    provider, identifier, title, price,
                    initial_price, lowest_price, lowest_price_at,
                    highest_price, highest_price_at, url,
                    status, hold_misses, created_at, last_updated,
                    last_fetched_epoch, version
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                """,
                (
                    provider_key,
                    identifier,
                    title,
                    price,
                    initial_price,
                    lowest_price,
                    lowest_price_at,
                    highest_price,
                    highest_price_at,
                    url or "",
                    status,
                    hold_misses,
                    created_at,
                    last_updated,
                    last_fetched_epoch,
                ),
            )
            article_id = int(cursor.lastrowid or 0)
            if record_initial_status and status in ("active", "finished"):
                cursor.execute(
                    """
                    INSERT INTO article_status_history (article_id, recorded_at, status)
                    VALUES (?, ?, ?)
                    """,
                    (article_id, created_at, status),
                )
            if search_id is not None:
                self._upsert_search_article_cursor(
                    cursor,
                    search_id=search_id,
                    article_id=article_id,
                    status=search_status,
                    hold_misses=search_hold_misses,
                    first_seen_at=created_at,
                    last_seen_at=last_updated or created_at,
                )
            return article_id, True, None

    def cas_update_article(
        self,
        *,
        article_id: int,
        new_title: str,
        new_price: float,
        lowest_price: float,
        lowest_price_at: str | None,
        highest_price: float,
        highest_price_at: str | None,
        url: str,
        status: str,
        hold_misses: int,
        last_updated: str,
        last_fetched_epoch: float,
        history_entry: dict[str, Any] | None = None,
        status_history_entry: dict[str, Any] | None = None,
    ) -> tuple[bool, dict[str, Any] | None]:
        self.ensure_schema()
        with self._transaction() as cursor:
            cursor.execute(
                """
                UPDATE articles
                SET title = ?,
                    price = ?,
                    lowest_price = ?,
                    lowest_price_at = ?,
                    highest_price = ?,
                    highest_price_at = ?,
                    url = CASE WHEN ? != '' THEN ? ELSE url END,
                    status = ?,
                    hold_misses = ?,
                    last_updated = ?,
                    last_fetched_epoch = MAX(last_fetched_epoch, ?),
                    version = version + 1
                WHERE id = ?
                  AND (ABS(price - ?) >= 0.0001 OR title != ?)
                  AND last_fetched_epoch <= ?
                """,
                (
                    new_title,
                    new_price,
                    lowest_price,
                    lowest_price_at,
                    highest_price,
                    highest_price_at,
                    url or "",
                    url or "",
                    status,
                    hold_misses,
                    last_updated,
                    last_fetched_epoch,
                    article_id,
                    new_price,
                    new_title,
                    last_fetched_epoch,
                ),
            )
            if cursor.rowcount == 0:
                cursor.execute("SELECT * FROM articles WHERE id = ?", (article_id,))
                current = cursor.fetchone()
                return False, dict(current) if current else None

            if history_entry is not None:
                cursor.execute(
                    """
                    INSERT INTO article_history (article_id, recorded_at, title, price)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        article_id,
                        str(history_entry["datetime"]),
                        history_entry.get("title"),
                        history_entry.get("price"),
                    ),
                )

            if status_history_entry is not None:
                cursor.execute(
                    """
                    INSERT INTO article_status_history (article_id, recorded_at, status)
                    VALUES (?, ?, ?)
                    """,
                    (
                        article_id,
                        str(status_history_entry["datetime"]),
                        str(status_history_entry["status"]),
                    ),
                )

            return True, None

    def update_article_status(
        self,
        *,
        article_id: int,
        status: str,
        hold_misses: int,
        last_fetched_epoch: float | None = None,
        status_history_entry: dict[str, Any] | None = None,
    ) -> None:
        self.ensure_schema()
        with self._transaction() as cursor:
            if last_fetched_epoch is not None:
                cursor.execute(
                    """
                    UPDATE articles
                    SET status = ?,
                        hold_misses = ?,
                        last_fetched_epoch = MAX(last_fetched_epoch, ?)
                    WHERE id = ?
                    """,
                    (status, hold_misses, last_fetched_epoch, article_id),
                )
            else:
                cursor.execute(
                    """
                    UPDATE articles
                    SET status = ?,
                        hold_misses = ?
                    WHERE id = ?
                    """,
                    (status, hold_misses, article_id),
                )

            if status_history_entry is not None:
                cursor.execute(
                    """
                    INSERT INTO article_status_history (article_id, recorded_at, status)
                    VALUES (?, ?, ?)
                    """,
                    (
                        article_id,
                        str(status_history_entry["datetime"]),
                        str(status_history_entry["status"]),
                    ),
                )

    def flush_search_cycle(
        self,
        *,
        search_id: int,
        is_first_run: bool,
        last_status: str,
        blocked_reason: str | None,
        last_synced_at: str,
        memberships: Sequence[SearchArticleState],
        global_status_updates: Sequence[tuple[int, str, int, dict[str, Any] | None]] = (),
        scrape_run: ScrapeRunRecord | None = None,
    ) -> None:
        self.ensure_schema()
        with self._transaction() as cursor:
            if memberships:
                cursor.executemany(
                    """
                    INSERT INTO search_articles (
                        search_id, article_id, status, hold_misses, first_seen_at, last_seen_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(search_id, article_id) DO UPDATE SET
                        status = excluded.status,
                        hold_misses = excluded.hold_misses,
                        last_seen_at = excluded.last_seen_at
                    """,
                    [
                        (
                            search_id,
                            item.article_id,
                            item.status,
                            item.hold_misses,
                            item.first_seen_at,
                            item.last_seen_at,
                        )
                        for item in memberships
                    ],
                )

            for article_id, status, hold_misses, status_entry in global_status_updates:
                cursor.execute(
                    "UPDATE articles SET status = ?, hold_misses = ? WHERE id = ?",
                    (status, hold_misses, article_id),
                )
                if status_entry is not None:
                    cursor.execute(
                        """
                        INSERT INTO article_status_history (article_id, recorded_at, status)
                        VALUES (?, ?, ?)
                        """,
                        (
                            article_id,
                            str(status_entry["datetime"]),
                            str(status_entry["status"]),
                        ),
                    )

            cursor.execute(
                """
                UPDATE searches
                SET is_first_run = ?,
                    last_status = ?,
                    blocked_reason = ?,
                    last_synced_at = ?
                WHERE id = ?
                """,
                (1 if is_first_run else 0, last_status, blocked_reason, last_synced_at, search_id),
            )

            if scrape_run is not None:
                cursor.execute(
                    """
                    INSERT INTO scrape_runs (
                        search_id, provider, started_at, finished_at, duration_s,
                        pages_fetched, scraped_count, new_count, updated_count,
                        missing_count, status, error_reason
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        scrape_run.search_id,
                        normalize_provider_key(scrape_run.provider),
                        scrape_run.started_at,
                        scrape_run.finished_at,
                        scrape_run.duration_s,
                        scrape_run.pages_fetched,
                        scrape_run.scraped_count,
                        scrape_run.new_count,
                        scrape_run.updated_count,
                        scrape_run.missing_count,
                        scrape_run.status,
                        scrape_run.error_reason,
                    ),
                )

    def record_notification_event(self, event: NotificationEventRecord) -> int:
        self.ensure_schema()
        with self._transaction() as cursor:
            cursor.execute(
                """
                INSERT INTO notification_events (
                    article_id, search_id, event_type, old_price, new_price,
                    percent_change, observer_name, delivery_status, error_message, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.article_id,
                    event.search_id,
                    event.event_type,
                    event.old_price,
                    event.new_price,
                    event.percent_change,
                    event.observer_name,
                    event.delivery_status,
                    event.error_message,
                    event.created_at,
                ),
            )
            return int(cursor.lastrowid or 0)

    def has_notification_event(
        self,
        *,
        article_id: int,
        event_type: str,
        new_price: float,
        observer_name: str = "telegram",
    ) -> bool:
        self.ensure_schema()
        with self._transaction() as cursor:
            cursor.execute(
                """
                SELECT id FROM notification_events
                WHERE article_id = ?
                  AND event_type = ?
                  AND ABS(new_price - ?) < 0.005
                  AND observer_name = ?
                  AND delivery_status = 'sent'
                LIMIT 1
                """,
                (article_id, event_type, new_price, observer_name),
            )
            return cursor.fetchone() is not None

    def get_cached_url(self, provider: str, cache_key: str) -> tuple[str, str] | None:
        self.ensure_schema()
        provider_key = normalize_provider_key(provider)
        with self._transaction() as cursor:
            cursor.execute(
                """
                SELECT resolved_segment, resolved_url
                FROM provider_url_cache
                WHERE provider = ? AND cache_key = ?
                LIMIT 1
                """,
                (provider_key, cache_key),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return str(row["resolved_segment"]), str(row["resolved_url"])

    def set_cached_url(
        self,
        *,
        provider: str,
        cache_key: str,
        resolved_segment: str,
        resolved_url: str,
        updated_at: str | None = None,
    ) -> None:
        self.ensure_schema()
        provider_key = normalize_provider_key(provider)
        ts = updated_at or str(datetime_lib.now())
        with self._transaction() as cursor:
            cursor.execute(
                """
                INSERT INTO provider_url_cache (
                    provider, cache_key, resolved_segment, resolved_url, updated_at
                )
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(provider, cache_key) DO UPDATE SET
                    resolved_segment = excluded.resolved_segment,
                    resolved_url = excluded.resolved_url,
                    updated_at = excluded.updated_at
                """,
                (provider_key, cache_key, resolved_segment, resolved_url, ts),
            )

    @staticmethod
    def _upsert_search_article_cursor(
        cursor: sqlite3.Cursor,
        *,
        search_id: int,
        article_id: int,
        status: str,
        hold_misses: int,
        first_seen_at: str,
        last_seen_at: str,
    ) -> None:
        cursor.execute(
            """
            INSERT INTO search_articles (
                search_id, article_id, status, hold_misses, first_seen_at, last_seen_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(search_id, article_id) DO UPDATE SET
                status = excluded.status,
                hold_misses = excluded.hold_misses,
                last_seen_at = excluded.last_seen_at
            """,
            (search_id, article_id, status, hold_misses, first_seen_at, last_seen_at),
        )


# ---------------------------------------------------------------------------
# Global Persistence Backend Resolution
# ---------------------------------------------------------------------------

_ACTIVE_BACKEND: PersistenceBackend | None = None
_BACKEND_LOCK = threading.RLock()


def set_persistence_backend(backend: PersistenceBackend | None) -> None:
    """Explicitly configure the active :class:`PersistenceBackend` (or ``None`` to disable)."""
    global _ACTIVE_BACKEND
    with _BACKEND_LOCK:
        _ACTIVE_BACKEND = backend


def get_persistence_backend(*, auto_init: bool = True) -> PersistenceBackend | None:
    """Return the active :class:`PersistenceBackend` when configured or reachable."""
    global _ACTIVE_BACKEND
    with _BACKEND_LOCK:
        if _ACTIVE_BACKEND is not None:
            return _ACTIVE_BACKEND
        if not auto_init:
            return None

        cfg = DatabaseConfig.from_env()
        if cfg.backend in ("json", "file", "none", "disabled"):
            return None
        if cfg.backend == "sqlite":
            sqlite_path = os.environ.get("SQLITE_DB_PATH", ":memory:")
            _ACTIVE_BACKEND = SQLitePersistenceBackend(sqlite_path)
            _ACTIVE_BACKEND.ensure_schema()
            return _ACTIVE_BACKEND

        mysql_backend = MySQLPersistenceBackend(cfg)
        if cfg.backend == "mysql":
            mysql_backend.ensure_schema()
            _ACTIVE_BACKEND = mysql_backend
            return _ACTIVE_BACKEND

        # "auto": use MySQL when reachable, otherwise return None so file fallback works seamlessly
        if mysql_backend.ping():
            mysql_backend.ensure_schema()
            _ACTIVE_BACKEND = mysql_backend
            return _ACTIVE_BACKEND
        return None


async def run_db_async(fn: Any, *args: Any, **kwargs: Any) -> Any:
    """Execute a synchronous database callable on the default thread-pool executor."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: fn(*args, **kwargs))
