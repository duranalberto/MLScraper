from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, Mock

from scraper.runtime.notifications import broadcast, broadcast_is_updated, parse_price


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
            element={"title": "New", "is_initial_scrape": True},
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
