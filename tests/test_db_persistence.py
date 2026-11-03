"""Tests for Hybrid In-Memory + Relational Database Persistence and Concurrency Rules."""

from __future__ import annotations

import asyncio
import logging
from typing import Any
import unittest
from unittest.mock import MagicMock, patch

import requests

from provider.liverpool import urls as lv_urls
from scraper.runtime.notifications import (
    NotificationDispatcher,
    NotificationEvent,
)
from shared.articles.article import MAX_HISTORY, Article
from shared.articles.catalog import (
    ProviderCatalog,
    get_provider_catalog,
    reset_provider_catalogs,
)
from shared.articles.status import Status
from shared.scraping.motor import Motor
from utils.db import (
    MYSQL_SCHEMA_DDL,
    DatabaseConfig,
    MySQLPersistenceBackend,
    SQLitePersistenceBackend,
    set_persistence_backend,
)


class CatalogMotor(Motor):
    """Test motor wired to a shared ProviderCatalog and scripted page responses."""

    PROVIDER_KEY = "ph"
    HOLD_MISS_THRESHOLD = 2

    def __init__(
        self,
        job_id: str,
        storage_path: str,
        pages: list[Any],
        *,
        catalog: ProviderCatalog,
        query_text: str | None = None,
    ) -> None:
        self.pages: list[Any] = list(pages)
        super().__init__(
            job_id=job_id,
            url=f"https://example.test/{storage_path}",
            storage_path=storage_path,
            debug=False,
            catalog=catalog,
            query_text=query_text,
        )
        self.PAGE_DELAY_RANGE = (0.0, 0.0)

    def scrape_page(self, body: dict):
        if not self.pages:
            return [], None
        return self.pages.pop(0)

    async def _fetch(self, session, url: str, retries: int = 3) -> str | None:
        return "<html></html>"


class HybridCatalogConcurrencyTests(unittest.IsolatedAsyncioTestCase):
    """Verify Rules 1–6 of the Hybrid In-Memory + Relational Database architecture."""

    def setUp(self) -> None:
        reset_provider_catalogs()
        self.backend = SQLitePersistenceBackend(":memory:")
        self.backend.ensure_schema()
        set_persistence_backend(self.backend)
        self.catalog = get_provider_catalog("ph", backend=self.backend)

    def tearDown(self) -> None:
        set_persistence_backend(None)
        reset_provider_catalogs()
        self.backend.close()

    async def test_rule1_concurrent_discovery_across_two_searches_first_writer_wins(self) -> None:
        """Rule 1: Same product discovered in two searches of the same store -> 1 DB row, 1 alert."""
        motor_macbook = CatalogMotor(
            "Macbook",
            "palacio_de_hierro/macbook.json",
            pages=[],
            catalog=self.catalog,
        )
        motor_apple = CatalogMotor(
            "Apple",
            "palacio_de_hierro/apple.json",
            pages=[],
            catalog=self.catalog,
        )
        motor_macbook.is_first_run = False
        motor_apple.is_first_run = False

        item_payload = {
            "identifier": "PH-MAC-1",
            "title": "MacBook Pro 14 M4",
            "price": 34999.0,
            "url": "https://www.elpalaciodehierro.com/macbook-pro-14.html",
        }
        motor_macbook.pages = [([dict(item_payload)], None)]
        motor_apple.pages = [([dict(item_payload)], None)]

        events: list[tuple[str, dict]] = []

        async def record_event(broadcast_type: str, element: dict) -> None:
            events.append((broadcast_type, element))

        await asyncio.gather(
            motor_macbook.scrape(caller=record_event, silent=True),
            motor_apple.scrape(caller=record_event, silent=True),
        )

        # Only ONE "new_element" event emitted across both concurrent searches
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0][0], "new_element")

        # Both motors point to the exact same canonical Article object in RAM
        self.assertEqual(len(motor_macbook.active), 1)
        self.assertEqual(len(motor_apple.active), 1)
        self.assertIs(motor_macbook.active.get_list()[0], motor_apple.active.get_list()[0])

        # Database has 1 canonical article and 2 search_articles links
        snapshot = self.backend.load_store_snapshot("ph")
        self.assertEqual(len(snapshot.articles), 1)
        self.assertEqual(snapshot.articles[0]["identifier"], "PH-MAC-1")
        self.assertEqual(
            sum(len(v) for v in snapshot.search_articles_by_search_id.values()),
            2,
        )

    async def test_rule2_concurrent_price_drop_idempotent_cas_updates_once(self) -> None:
        """Rule 2: Same price drop scraped by two searches -> 1 history entry, 1 update alert."""
        motor_macbook = CatalogMotor(
            "Macbook",
            "palacio_de_hierro/macbook.json",
            pages=[
                (
                    [
                        {
                            "identifier": "PH-MAC-2",
                            "title": "MacBook Air M3",
                            "price": 25000.0,
                            "url": "https://example.test/mba",
                        }
                    ],
                    None,
                )
            ],
            catalog=self.catalog,
        )
        motor_apple = CatalogMotor(
            "Apple",
            "palacio_de_hierro/apple.json",
            pages=[
                (
                    [
                        {
                            "identifier": "PH-MAC-2",
                            "title": "MacBook Air M3",
                            "price": 25000.0,
                            "url": "https://example.test/mba",
                        }
                    ],
                    None,
                )
            ],
            catalog=self.catalog,
        )
        await motor_macbook.scrape(silent=True)
        await motor_apple.scrape(silent=True)

        # Now drop price from 25,000 -> 19,999 in both searches
        discounted = {
            "identifier": "PH-MAC-2",
            "title": "MacBook Air M3",
            "price": 19999.0,
            "url": "https://example.test/mba",
        }
        motor_macbook.pages = [([dict(discounted)], None)]
        motor_apple.pages = [([dict(discounted)], None)]

        events: list[tuple[str, dict]] = []

        async def record_event(broadcast_type: str, element: dict) -> None:
            events.append((broadcast_type, element))

        await asyncio.gather(
            motor_macbook.scrape(caller=record_event, silent=True),
            motor_apple.scrape(caller=record_event, silent=True),
        )

        # Strictly one update event and one history entry
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0][0], "is_updated")

        canonical = self.catalog.articles_by_id["PH-MAC-2"]
        self.assertEqual(canonical.price, 19999.0)
        self.assertEqual(canonical.initial_price, 25000.0)
        self.assertEqual(canonical.lowest_price, 19999.0)
        self.assertEqual(canonical.highest_price, 25000.0)
        self.assertEqual(len(canonical.history), 1)
        self.assertEqual(canonical.history[0].price, 25000.0)

        # Both motors see $19,999 immediately in their in-memory active streams
        self.assertEqual(motor_macbook.active.get_list()[0].price, 19999.0)
        self.assertEqual(motor_apple.active.get_list()[0].price, 19999.0)

        snapshot = self.backend.load_store_snapshot("ph")
        article_id = int(snapshot.articles[0]["id"])
        self.assertEqual(len(snapshot.history_by_article_id[article_id]), 1)

    def test_rule3_stale_page_fetch_epoch_does_not_revert_newer_price(self) -> None:
        """Rule 3: Out-of-order CDN page with older fetched_epoch cannot overwrite fresher price."""
        motor_a = CatalogMotor(
            "Macbook", "palacio_de_hierro/macbook.json", [], catalog=self.catalog
        )
        motor_b = CatalogMotor("Apple", "palacio_de_hierro/apple.json", [], catalog=self.catalog)

        # Search B observes fresh page at t=200.0 with new price $16,000
        article_b, is_new_b, _ = motor_b.save(
            {"identifier": "PH-EPOCH", "title": "iMac M4", "price": 20000.0},
            fetched_epoch=100.0,
        )
        self.assertTrue(is_new_b)
        assert article_b is not None

        _, _, is_upd_b = motor_b.save(
            {"identifier": "PH-EPOCH", "title": "iMac M4", "price": 16000.0},
            fetched_epoch=200.0,
        )
        self.assertTrue(is_upd_b)
        self.assertEqual(article_b.price, 16000.0)

        # Search A finishes parsing an older cached page from t=150.0 showing old price $20,000
        article_a, is_new_a, is_upd_a = motor_a.save(
            {"identifier": "PH-EPOCH", "title": "iMac M4", "price": 20000.0},
            fetched_epoch=150.0,
        )
        self.assertFalse(is_new_a)
        self.assertFalse(is_upd_a)
        assert article_a is not None
        self.assertEqual(article_a.price, 16000.0)
        self.assertIn(article_a, motor_a.active)

    async def test_rule4_disappearance_in_search_a_while_active_in_search_b_strict_dominance(
        self,
    ) -> None:
        """Rule 4: Product missing in Search A transitions in Search A but stays active globally."""
        item = {"identifier": "PH-DOM-1", "title": "Mac mini M4", "price": 14999.0}
        motor_a = CatalogMotor(
            "Macbook",
            "palacio_de_hierro/macbook.json",
            pages=[([dict(item)], None)],
            catalog=self.catalog,
        )
        motor_b = CatalogMotor(
            "Computadoras Apple",
            "palacio_de_hierro/computadoras-apple.json",
            pages=[([dict(item)], None)],
            catalog=self.catalog,
        )
        await motor_a.scrape(silent=True)
        await motor_b.scrape(silent=True)

        # Cycle 2 & 3: Product disappears from Search A, but remains present in Search B
        motor_a.pages = [([], None)]
        motor_b.pages = [([dict(item)], None)]
        await motor_a.scrape(silent=True)
        await motor_b.scrape(silent=True)

        self.assertEqual(len(motor_a.active), 0)
        self.assertEqual(len(motor_a.on_hold), 1)
        self.assertEqual(len(motor_b.active), 1)
        # Global status MUST remain active because Search B still sees it!
        canonical = self.catalog.articles_by_id["PH-DOM-1"]
        self.assertEqual(canonical.status, Status.active)

        # Cycle 3: Search A misses it again -> reaches HOLD_MISS_THRESHOLD (2) -> finished in Search A
        motor_a.pages = [([], None)]
        motor_b.pages = [([dict(item)], None)]
        await motor_a.scrape(silent=True)
        await motor_b.scrape(silent=True)

        self.assertEqual(len(motor_a.on_hold), 0)
        self.assertEqual(len(motor_a.finished), 1)
        self.assertEqual(len(motor_b.active), 1)
        self.assertEqual(canonical.status, Status.active)

        # Cycle 4 & 5: Now Search B also misses it twice -> global status transitions on_hold -> finished
        motor_b.pages = [([], None)]
        await motor_b.scrape(silent=True)
        self.assertEqual(canonical.status, Status.on_hold)

        motor_b.pages = [([], None)]
        await motor_b.scrape(silent=True)
        self.assertEqual(canonical.status, Status.finished)
        self.assertEqual(canonical.status_history[0].status, Status.finished)

    async def test_rule5_product_moves_from_search_a_to_search_b_without_false_new_alert(
        self,
    ) -> None:
        """Rule 5: Product on_hold in Search A appearing in Search B reactivates without new alert."""
        item = {"identifier": "PH-MOVE-1", "title": "Studio Display", "price": 39999.0}
        motor_a = CatalogMotor(
            "Macbook",
            "palacio_de_hierro/macbook.json",
            pages=[([dict(item)], None), ([], None)],
            catalog=self.catalog,
        )
        motor_b = CatalogMotor(
            "Apple",
            "palacio_de_hierro/apple.json",
            pages=[([], None), ([dict(item)], None)],
            catalog=self.catalog,
        )
        await motor_a.scrape(silent=True)
        await motor_b.scrape(silent=True)

        # Cycle 2: disappears in A (goes on_hold), appears for the first time in B
        await motor_a.scrape(silent=True)
        self.assertEqual(self.catalog.articles_by_id["PH-MOVE-1"].status, Status.on_hold)

        events: list[tuple[str, dict]] = []

        async def record_event(broadcast_type: str, element: dict) -> None:
            events.append((broadcast_type, element))

        await motor_b.scrape(caller=record_event, silent=True)

        # Not a new product to the store -> 0 notifications, reactivated globally
        self.assertEqual(events, [])
        self.assertEqual(self.catalog.articles_by_id["PH-MOVE-1"].status, Status.active)
        self.assertIn(self.catalog.articles_by_id["PH-MOVE-1"], motor_b.active)

    async def test_rule6_disabled_search_does_not_keep_article_globally_active(self) -> None:
        """Rule 6: Archived searches (is_enabled=0) are ignored by Strict Status Dominance."""
        item = {"identifier": "PH-ARCH-1", "title": "iPod Touch", "price": 4999.0}
        motor_archived = CatalogMotor(
            "Archived Search",
            "palacio_de_hierro/archived.json",
            pages=[([dict(item)], None)],
            catalog=self.catalog,
        )
        motor_active = CatalogMotor(
            "Active Search",
            "palacio_de_hierro/active.json",
            pages=[([dict(item)], None)],
            catalog=self.catalog,
        )
        await motor_archived.scrape(silent=True)
        await motor_active.scrape(silent=True)

        # Mark 'archived.json' disabled
        self.backend.mark_unlisted_searches_disabled(
            {"palacio_de_hierro/active.json"}, provider="ph"
        )
        self.catalog.search_records_by_id[motor_archived.search_id].is_enabled = False
        self.catalog.search_memberships["PH-ARCH-1"][
            motor_archived.search_id
        ].is_search_enabled = False

        # Now product disappears from Active Search
        motor_active.pages = [([], None)]
        await motor_active.scrape(silent=True)
        self.assertEqual(self.catalog.articles_by_id["PH-ARCH-1"].status, Status.on_hold)

        motor_active.pages = [([], None)]
        await motor_active.scrape(silent=True)
        self.assertEqual(self.catalog.articles_by_id["PH-ARCH-1"].status, Status.finished)


class ValuableDataPersistenceTests(unittest.IsolatedAsyncioTestCase):
    """Verify price watermarks, notification audit log, scrape_runs, and Liverpool URL cache."""

    def setUp(self) -> None:
        reset_provider_catalogs()
        self.backend = SQLitePersistenceBackend(":memory:")
        self.backend.ensure_schema()
        set_persistence_backend(self.backend)

    def tearDown(self) -> None:
        set_persistence_backend(None)
        reset_provider_catalogs()
        self.backend.close()

    def test_price_watermarks_survive_history_truncation(self) -> None:
        """initial_price, lowest_price, and highest_price persist beyond MAX_HISTORY=100."""
        article = Article("ID-1", "GPU", 10000.0, datetime="2026-01-01")
        self.assertEqual(article.initial_price, 10000.0)
        self.assertEqual(article.lowest_price, 10000.0)
        self.assertEqual(article.highest_price, 10000.0)

        article.update({"price": 7500.0})  # all-time low
        article.update({"price": 15000.0})  # all-time high

        for i in range(MAX_HISTORY + 10):
            article.update({"price": 9000.0 + float(i)})

        self.assertEqual(len(article.history), MAX_HISTORY)
        self.assertEqual(article.initial_price, 10000.0)
        self.assertEqual(article.lowest_price, 7500.0)
        self.assertEqual(article.highest_price, 15000.0)

    async def test_notification_dispatcher_records_audit_and_deduplicates_identical_transition(
        self,
    ) -> None:
        """NotificationDispatcher logs sent notifications and prevents duplicate re-alerts."""
        article_id, _, _ = self.backend.insert_or_get_article(
            provider="az",
            identifier="B001",
            title="Kindle",
            price=2000.0,
            initial_price=2500.0,
            lowest_price=2000.0,
            lowest_price_at="2026-11-03",
            highest_price=2500.0,
            highest_price_at="2026-11-01",
            url="https://amazon.com.mx/dp/B001",
            status="active",
            hold_misses=0,
            created_at="2026-11-01",
            last_updated="2026-11-03",
            last_fetched_epoch=1.0,
        )

        received: list[NotificationEvent] = []

        class RecordingObserver:
            async def notify(self, event: NotificationEvent) -> None:
                received.append(event)

        dispatcher = NotificationDispatcher(
            logging.getLogger("test.notif"),
            observers=[RecordingObserver()],
            backend=self.backend,
        )
        payload = {
            "identifier": "B001",
            "article_id": article_id,
            "title": "Kindle",
            "price": 2000.0,
            "history": [{"datetime": "2026-11-01", "price": 2500.0}],
            "url": "https://amazon.com.mx/dp/B001",
        }

        await dispatcher.broadcast("is_updated", dict(payload))
        await dispatcher.broadcast("is_updated", dict(payload))

        self.assertEqual(len(received), 1)
        self.assertTrue(
            self.backend.has_notification_event(
                article_id=article_id,
                event_type="price_drop",
                new_price=2000.0,
                observer_name="recording",
            )
        )

    def test_liverpool_url_resolver_caches_and_falls_back_on_request_failure(self) -> None:
        """provider_url_cache saves resolved Liverpool tokens and serves fallback on outage."""
        lv_urls._resolve_seller_filtered_segment.cache_clear()
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {
            "mainContent": {
                "encryptedFilters": "N-cachedtoken123",
                "selectedNavigation": [
                    {
                        "name": lv_urls.LIVERPOOL_SELLER_REFINEMENT_NAME,
                        "refinements": [{"value": lv_urls.LIVERPOOL_SELLER_REFINEMENT_VALUE}],
                    }
                ],
            }
        }

        with patch("provider.liverpool.urls.requests.post", return_value=mock_response):
            segment = lv_urls._resolve_seller_filtered_segment(query="macbook")
        self.assertEqual(segment, "N-cachedtoken123")
        self.assertEqual(
            self.backend.get_cached_url("lv", "macbook::"),
            ("N-cachedtoken123", "https://www.liverpool.com.mx/tienda/N-cachedtoken123"),
        )

        # Clear in-memory LRU cache and simulate Liverpool API network outage
        lv_urls._resolve_seller_filtered_segment.cache_clear()
        with patch(
            "provider.liverpool.urls.requests.post",
            side_effect=requests.RequestException("API timeout"),
        ):
            fallback_segment = lv_urls._resolve_seller_filtered_segment(query="macbook")
        self.assertEqual(fallback_segment, "N-cachedtoken123")
        lv_urls._resolve_seller_filtered_segment.cache_clear()


class MySQLPersistenceBackendUnitTests(unittest.TestCase):
    """Verify MySQLPersistenceBackend SQL execution against mocked PyMySQL connections."""

    def test_mysql_schema_ddl_and_operations_execute_expected_sql(self) -> None:
        self.assertEqual(len(MYSQL_SCHEMA_DDL), 8)
        executed_sql: list[str] = []

        mock_cursor = MagicMock()

        def execute_side_effect(sql: str, params=None):
            executed_sql.append(" ".join(sql.split()))
            if "SELECT * FROM searches" in sql:
                mock_cursor.fetchone.return_value = {
                    "id": 7,
                    "provider": "ph",
                    "job_id": "Macbook",
                    "storage_path": "palacio_de_hierro/macbook.json",
                    "is_enabled": 1,
                    "is_first_run": 1,
                    "query_text": "macbook",
                    "resolved_url": "https://example.test",
                    "filter_config": '{"page": "macbook"}',
                    "last_status": "ok",
                    "blocked_reason": None,
                    "last_synced_at": None,
                }
            elif "SELECT * FROM articles WHERE provider" in sql:
                mock_cursor.fetchone.return_value = None
            elif "INSERT INTO articles" in sql:
                mock_cursor.lastrowid = 42
            elif "UPDATE articles" in sql:
                mock_cursor.rowcount = 1

        mock_cursor.execute.side_effect = execute_side_effect
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        backend = MySQLPersistenceBackend(DatabaseConfig(backend="mysql"))
        with patch.object(backend, "_connect", return_value=mock_conn):
            backend.ensure_schema()
            search = backend.upsert_search(
                provider="ph",
                job_id="Macbook",
                storage_path="palacio_de_hierro/macbook.json",
                query_text="macbook",
                resolved_url="https://example.test",
                filter_config={"page": "macbook"},
            )
            self.assertEqual(search.id, 7)

            aid, inserted, _ = backend.insert_or_get_article(
                provider="ph",
                identifier="SKU-1",
                title="MacBook",
                price=20000.0,
                initial_price=20000.0,
                lowest_price=20000.0,
                lowest_price_at="2026-11-03",
                highest_price=20000.0,
                highest_price_at="2026-11-03",
                url="https://example.test/1",
                status="active",
                hold_misses=0,
                created_at="2026-11-03",
                last_updated=None,
                last_fetched_epoch=10.0,
                search_id=search.id,
            )
            self.assertEqual(aid, 42)
            self.assertTrue(inserted)

            cas_ok, _ = backend.cas_update_article(
                article_id=42,
                new_title="MacBook Pro",
                new_price=18000.0,
                lowest_price=18000.0,
                lowest_price_at="2026-11-03",
                highest_price=20000.0,
                highest_price_at="2026-11-03",
                url="https://example.test/1",
                status="active",
                hold_misses=0,
                last_updated="2026-11-03",
                last_fetched_epoch=20.0,
                history_entry={"datetime": "2026-11-03", "price": 20000.0},
            )
            self.assertTrue(cas_ok)

        self.assertTrue(any("CREATE TABLE IF NOT EXISTS articles" in s for s in executed_sql))
        self.assertTrue(
            any("CREATE TABLE IF NOT EXISTS notification_events" in s for s in executed_sql)
        )
        self.assertTrue(any("CREATE TABLE IF NOT EXISTS scrape_runs" in s for s in executed_sql))
        self.assertTrue(
            any("CREATE TABLE IF NOT EXISTS provider_url_cache" in s for s in executed_sql)
        )
