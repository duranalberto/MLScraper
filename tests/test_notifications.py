from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, Mock

from scraper.runtime.notifications import (
    NotificationDispatcher,
    NotificationEvent,
    NotificationEventType,
    broadcast,
    broadcast_is_updated,
    broadcast_new_element,
    parse_price,
)
from scraper.runtime.telegram_notifications import TelegramNotifier, TelegramObserver


class ParsePriceTests(unittest.TestCase):
    def test_parse_price_accepts_numeric_and_comma_separated_strings(self) -> None:
        self.assertEqual(parse_price(123), 123.0)
        self.assertEqual(parse_price(123.45), 123.45)
        self.assertEqual(parse_price("1,234.50"), 1234.5)

    def test_parse_price_returns_none_for_empty_or_unparseable_values(self) -> None:
        self.assertIsNone(parse_price(None))
        self.assertIsNone(parse_price(""))
        self.assertIsNone(parse_price("not a price"))
        self.assertIsNone(parse_price(object()))


class BroadcastRoutingTests(unittest.IsolatedAsyncioTestCase):
    async def test_broadcast_routes_new_and_updated_events(self) -> None:
        send_new = AsyncMock()
        send_price_drop = AsyncMock()
        logger = Mock()

        await broadcast(
            broadcast_type="new_element",
            element={"title": "New", "is_initial_scrape": False},
            send_new=send_new,
            send_price_drop=send_price_drop,
            logger=logger,
        )
        await broadcast(
            broadcast_type="is_updated",
            element={
                "title": "Drop",
                "price": 80.0,
                "url": "https://example.test/item",
                "history": [{"price": 100.0, "datetime": "2026-01-01"}],
            },
            send_new=send_new,
            send_price_drop=send_price_drop,
            logger=logger,
        )

        send_new.assert_awaited_once()
        send_price_drop.assert_awaited_once()

    async def test_unknown_broadcast_type_is_logged_and_ignored(self) -> None:
        send_new = AsyncMock()
        send_price_drop = AsyncMock()
        logger = Mock()

        await broadcast(
            broadcast_type="unknown",
            element={},
            send_new=send_new,
            send_price_drop=send_price_drop,
            logger=logger,
        )

        logger.warning.assert_called_once()
        send_new.assert_not_awaited()
        send_price_drop.assert_not_awaited()


class NewElementBroadcastTests(unittest.IsolatedAsyncioTestCase):
    async def test_initial_scrape_new_item_is_not_sent(self) -> None:
        send_new = AsyncMock()
        logger = Mock()

        await broadcast_new_element(
            {
                "job_id": "New job",
                "title": "Baseline item",
                "is_initial_scrape": True,
            },
            send_new=send_new,
            logger=logger,
        )

        send_new.assert_not_awaited()
        logger.info.assert_not_called()

    async def test_non_initial_new_item_is_sent(self) -> None:
        send_new = AsyncMock()
        logger = Mock()
        element = {
            "job_id": "Existing job",
            "title": "New arrival",
            "price": 100.0,
            "url": "https://example.test/item",
        }

        await broadcast_new_element(
            element,
            send_new=send_new,
            logger=logger,
        )

        send_new.assert_awaited_once_with(element)
        logger.info.assert_called_once()


class PriceDropBroadcastTests(unittest.IsolatedAsyncioTestCase):
    async def test_price_drop_under_threshold_is_not_sent(self) -> None:
        send_price_drop = AsyncMock()
        logger = Mock()

        await broadcast_is_updated(
            {
                "title": "Small drop",
                "price": 87.0,
                "history": [{"price": 100.0, "datetime": "2026-01-01"}],
            },
            send_price_drop=send_price_drop,
            logger=logger,
        )

        send_price_drop.assert_not_awaited()
        logger.info.assert_not_called()

    async def test_exact_threshold_price_drop_is_sent(self) -> None:
        send_price_drop = AsyncMock()
        logger = Mock()
        element = {
            "title": "Threshold drop",
            "price": 86.0,
            "url": "https://example.test/item",
            "history": [{"price": 100.0, "datetime": "2026-01-01"}],
        }

        await broadcast_is_updated(
            element,
            send_price_drop=send_price_drop,
            logger=logger,
        )

        self.assertEqual(element["percent_change"], "14.00")
        self.assertEqual(element["previous_price"], 100.0)
        self.assertEqual(element["new_price"], 86.0)
        send_price_drop.assert_awaited_once_with(element)

    async def test_missing_or_unparseable_history_price_is_ignored(self) -> None:
        send_price_drop = AsyncMock()
        logger = Mock()

        await broadcast_is_updated(
            {"title": "No history", "price": 1.0, "history": []},
            send_price_drop=send_price_drop,
            logger=logger,
        )
        await broadcast_is_updated(
            {"title": "Bad price", "price": 1.0, "history": [{"price": "bad"}]},
            send_price_drop=send_price_drop,
            logger=logger,
        )

        send_price_drop.assert_not_awaited()


class NotificationDispatcherQueueAndObserverTests(unittest.IsolatedAsyncioTestCase):
    async def test_running_dispatcher_enqueues_without_blocking_caller(self) -> None:
        observer_started = asyncio.Event()
        release_observer = asyncio.Event()
        received: list[NotificationEvent] = []

        class SlowObserver:
            async def notify(self, event: NotificationEvent) -> None:
                observer_started.set()
                await release_observer.wait()
                received.append(event)

        dispatcher = NotificationDispatcher(Mock(), observers=[SlowObserver()])
        dispatcher.start()
        try:
            await asyncio.wait_for(
                dispatcher.broadcast(
                    "new_element",
                    {
                        "job_id": "Macbook",
                        "title": "MacBook Pro",
                        "price": 25000.0,
                        "url": "https://example.test/mac",
                        "is_initial_scrape": False,
                    },
                ),
                timeout=0.05,
            )
            await asyncio.wait_for(observer_started.wait(), timeout=0.5)
            self.assertEqual(len(received), 0)

            release_observer.set()
            await dispatcher.stop(drain=True)
            self.assertEqual(len(received), 1)
            self.assertEqual(received[0].event_type, NotificationEventType.NEW_ELEMENT)
        finally:
            release_observer.set()
            await dispatcher.stop(drain=False)

    async def test_dispatcher_fans_out_to_multiple_observers_and_isolates_failures(self) -> None:
        events_a: list[NotificationEvent] = []
        events_b: list[NotificationEvent] = []

        class FailingObserver:
            async def notify(self, event: NotificationEvent) -> None:
                raise RuntimeError("observer transport down")

        class RecordingObserver:
            def __init__(self, target: list[NotificationEvent]) -> None:
                self.target = target

            async def notify(self, event: NotificationEvent) -> None:
                self.target.append(event)

        logger = Mock()
        obs_a = RecordingObserver(events_a)
        obs_b = RecordingObserver(events_b)
        dispatcher = TelegramNotifier(logger, observers=[obs_a, FailingObserver()])
        dispatcher.add_observer(obs_b)
        dispatcher.start()
        try:
            await dispatcher.broadcast(
                "is_updated",
                {
                    "title": "Switch 2",
                    "price": 8000.0,
                    "url": "https://example.test/switch2",
                    "history": [{"price": 10000.0, "datetime": "2026-01-01"}],
                },
            )
            await dispatcher.stop(drain=True)
        finally:
            await dispatcher.stop(drain=False)

        self.assertEqual(len(events_a), 1)
        self.assertEqual(len(events_b), 1)
        self.assertEqual(events_a[0].event_type, NotificationEventType.PRICE_DROP)
        self.assertEqual(events_a[0].element["percent_change"], "20.00")
        logger.error.assert_called_once()
        self.assertIsInstance(TelegramObserver(), object)
