from __future__ import annotations

import asyncio
import unittest
from typing import Any, cast
from unittest.mock import AsyncMock, patch

from aiohttp import ClientSession

from shared.articles.article import Article
from shared.scraping.motor import Motor


class ScriptedMotor(Motor):
    PROVIDER_KEY = "scripted"

    def __init__(self, pages: list[tuple[list[dict], str | None] | Exception]) -> None:
        self.pages = pages
        self.fetched_urls: list[str] = []
        super().__init__(
            search_term="Scripted Search",
            url="https://example.test/page-1",
            storage_path="tests/scripted.json",
            debug=False,
        )
        self.PAGE_DELAY_RANGE = (0.0, 0.0)

    def scrape_page(self, body: dict) -> tuple[list[Any], str | None]:
        result = self.pages.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    async def _fetch(
        self,
        session: ClientSession,
        url: str,
        retries: int = 3,
    ) -> str | None:
        self.fetched_urls.append(url)
        return "<html></html>"


def make_motor(pages: list[tuple[list[dict], str | None] | Exception]) -> ScriptedMotor:
    with patch("shared.articles.repository.read_json_file", return_value=[]):
        return ScriptedMotor(pages)


class MotorScrapePageTests(unittest.IsolatedAsyncioTestCase):
    async def test_fetch_failure_marks_scrape_incomplete_and_stops_page(self) -> None:
        motor = make_motor([])
        motor._fetch = AsyncMock(return_value=None)  # type: ignore[method-assign]
        results: list[Article] = []

        next_url = await motor._scrape_page(
            session=cast(ClientSession, None),
            current_url=motor.url,
            results=results,
            caller=None,
            silent=True,
        )

        self.assertIsNone(next_url)
        self.assertTrue(motor._scrape_incomplete)
        self.assertEqual(motor.blocked_reason, "fetch_failed")
        self.assertEqual(results, [])

    async def test_parser_exception_marks_parse_error(self) -> None:
        motor = make_motor([RuntimeError("bad markup")])
        results: list[Article] = []

        next_url = await motor._scrape_page(
            session=cast(ClientSession, None),
            current_url=motor.url,
            results=results,
            caller=None,
            silent=True,
        )

        self.assertIsNone(next_url)
        self.assertTrue(motor._scrape_incomplete)
        self.assertEqual(motor.blocked_reason, "parse_error")

    async def test_empty_paginated_page_marks_incomplete_without_reconciling(self) -> None:
        motor = make_motor([([], "https://example.test/page-2")])
        motor.BLOCKED_BACKOFF_SECONDS = 25
        results: list[Article] = []

        next_url = await motor._scrape_page(
            session=cast(ClientSession, None),
            current_url=motor.url,
            results=results,
            caller=None,
            silent=True,
        )

        self.assertIsNone(next_url)
        self.assertTrue(motor._scrape_incomplete)
        self.assertEqual(motor.blocked_reason, "empty_paginated_page")

    async def test_new_item_callback_includes_search_term_and_initial_flag(self) -> None:
        motor = make_motor(
            [
                (
                    [
                        {
                            "identifier": "item",
                            "title": "Console",
                            "price": 100.0,
                            "url": "https://example.test/item",
                        }
                    ],
                    None,
                )
            ]
        )
        caller = AsyncMock()
        results: list[Article] = []

        await motor._scrape_page(
            session=cast(ClientSession, None),
            current_url=motor.url,
            results=results,
            caller=caller,
            silent=True,
        )

        caller.assert_awaited_once()
        call = caller.await_args
        assert call is not None
        kwargs = call.kwargs
        self.assertEqual(kwargs["broadcast_type"], "new_element")
        self.assertEqual(kwargs["element"]["search_term"], "Scripted Search")
        self.assertTrue(kwargs["element"]["is_initial_scrape"])

    async def test_updated_item_callback_uses_is_updated_payload_without_initial_flag(self) -> None:
        motor = make_motor(
            [
                (
                    [
                        {
                            "identifier": "item",
                            "title": "Console",
                            "price": 80.0,
                            "url": "https://example.test/item",
                        }
                    ],
                    None,
                )
            ]
        )
        motor.is_first_run = False
        motor.active.add(
            Article(
                "item",
                "Console",
                100.0,
                "https://example.test/item",
                datetime="2026-01-01",
            )
        )
        caller = AsyncMock()
        results: list[Article] = []

        await motor._scrape_page(
            session=cast(ClientSession, None),
            current_url=motor.url,
            results=results,
            caller=caller,
            silent=True,
        )

        call = caller.await_args
        assert call is not None
        kwargs = call.kwargs
        self.assertEqual(kwargs["broadcast_type"], "is_updated")
        self.assertEqual(kwargs["element"]["history"][0]["price"], 100.0)
        self.assertNotIn("is_initial_scrape", kwargs["element"])


class MotorScrapeIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_completed_scrape_reconciles_missing_active_item_to_on_hold(self) -> None:
        motor = make_motor([([], None)])
        motor.active.add(Article("missing", "Missing", 10.0))
        motor.save_to_file = AsyncMock()  # type: ignore[method-assign]

        await motor.scrape(silent=True)

        self.assertEqual(len(motor.active), 0)
        self.assertEqual([article.identifier for article in motor.on_hold], ["missing"])
        motor.save_to_file.assert_awaited_once()

    async def test_incomplete_scrape_skips_missing_item_reconciliation(self) -> None:
        motor = make_motor([])
        motor.active.add(Article("existing", "Existing", 10.0))
        motor._fetch = AsyncMock(return_value=None)  # type: ignore[method-assign]
        motor.save_to_file = AsyncMock()  # type: ignore[method-assign]

        await motor.scrape(silent=True)

        self.assertEqual([article.identifier for article in motor.active], ["existing"])
        self.assertEqual(len(motor.on_hold), 0)
        motor.save_to_file.assert_awaited_once()

    async def test_blocked_until_skips_scrape_without_saving(self) -> None:
        motor = make_motor([([], None)])
        motor.save_to_file = AsyncMock()  # type: ignore[method-assign]
        motor.mark_blocked("rate_limited", cooldown=60)

        await motor.scrape(silent=True)

        self.assertEqual(motor.fetched_urls, [])
        motor.save_to_file.assert_not_awaited()

    async def test_fresh_session_per_page_fetches_each_page_with_new_session(self) -> None:
        motor = make_motor(
            [
                (
                    [{"identifier": "one", "title": "One", "price": 1.0}],
                    "https://example.test/page-2",
                ),
                ([{"identifier": "two", "title": "Two", "price": 2.0}], None),
            ]
        )
        motor.FRESH_SESSION_PER_PAGE = True
        motor.save_to_file = AsyncMock()  # type: ignore[method-assign]

        with patch("shared.scraping.motor.asyncio.sleep", new=AsyncMock()):
            await motor.scrape(silent=True)

        self.assertEqual(
            motor.fetched_urls, ["https://example.test/page-1", "https://example.test/page-2"]
        )
        self.assertEqual([article.identifier for article in motor.active], ["two", "one"])

    async def test_first_run_logs_single_notification_skip_notice(self) -> None:
        motor = make_motor(
            [
                (
                    [
                        {"identifier": "one", "title": "One", "price": 1.0},
                        {"identifier": "two", "title": "Two", "price": 2.0},
                    ],
                    None,
                )
            ]
        )
        caller = AsyncMock()
        motor.save_to_file = AsyncMock()  # type: ignore[method-assign]

        with patch("shared.scraping.motor.logger") as logger:
            await motor.scrape(caller=caller, silent=False)

        skip_logs = [
            call
            for call in logger.info.call_args_list
            if "first run: Telegram notifications will be skipped" in call.args[0]
        ]
        self.assertEqual(len(skip_logs), 1)
        self.assertEqual(caller.await_count, 2)


class MotorUtilityTests(unittest.IsolatedAsyncioTestCase):
    async def test_mark_blocked_sets_deadline_inside_running_loop(self) -> None:
        motor = make_motor([])

        motor.mark_blocked("blocked", cooldown=10)

        self.assertEqual(motor.blocked_reason, "blocked")
        self.assertGreater(motor.blocked_until, asyncio.get_running_loop().time())

    async def test_retry_after_delay_caps_and_defaults_values(self) -> None:
        motor = make_motor([])
        motor.RATE_LIMIT_SLEEP_CAP = 30

        self.assertEqual(motor._retry_after_delay(None), 60.0)
        self.assertEqual(motor._retry_after_delay("bad"), 60.0)
        self.assertEqual(motor._retry_after_delay("-1"), 0.0)
        self.assertEqual(motor._retry_after_delay("120"), 30.0)
