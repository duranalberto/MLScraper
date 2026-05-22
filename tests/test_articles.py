from __future__ import annotations

import unittest
from typing import Any, cast

from shared.articles.article import Article, MAX_HISTORY, StatusHistory
from shared.articles.lifecycle import ArticleLifecycle
from shared.articles.status import Status
from shared.articles.stream import Stream


class ArticleTests(unittest.TestCase):
    def test_update_records_previous_values_and_uses_previous_last_updated(self) -> None:
        article = Article("item", "Old title", 100.0, datetime="created")

        self.assertTrue(article.update({"title": "New title", "price": 80.0}))
        first_last_updated = article.last_updated
        self.assertEqual(
            article.history[0].dump(), {"datetime": "created", "title": "Old title", "price": 100.0}
        )

        self.assertTrue(article.update({"price": 70.0}))
        self.assertEqual(article.history[0].datetime, first_last_updated)
        self.assertEqual(article.history[0].price, 80.0)

    def test_update_noops_when_title_and_price_are_unchanged(self) -> None:
        article = Article("item", "Title", 100.0)

        self.assertFalse(article.update({"title": "Title", "price": 100.0}))
        self.assertEqual(article.history, [])
        self.assertIsNone(article.last_updated)

    def test_history_is_truncated_to_max_history(self) -> None:
        article = Article("item", "Title 0", 0.0)

        for index in range(MAX_HISTORY + 5):
            article.update({"title": f"Title {index + 1}", "price": float(index + 1)})

        self.assertEqual(len(article.history), MAX_HISTORY)

    def test_invalid_embedded_history_and_hold_misses_are_normalized(self) -> None:
        article = Article(
            "item",
            "Title",
            100.0,
            history=cast(Any, [{"datetime": "ok", "price": "90"}, {"datetime": ""}]),
            status_history=cast(
                Any,
                [
                    {"datetime": "ok", "status": "finished"},
                    {"datetime": "bad", "status": "unknown"},
                ],
            ),
            hold_misses=-3,
        )

        self.assertEqual(len(article.history), 1)
        self.assertEqual(len(article.status_history), 1)
        self.assertEqual(article.status_history[0], StatusHistory("ok", Status.finished))
        self.assertEqual(article.hold_misses, 0)

    def test_status_history_skips_on_hold_and_consecutive_duplicates(self) -> None:
        article = Article("item", "Title", 100.0)

        self.assertFalse(article.record_status_history(Status.on_hold))
        self.assertTrue(article.record_status_history(Status.finished))
        self.assertFalse(article.record_status_history(Status.finished))

        self.assertEqual([history.status for history in article.status_history], [Status.finished])

    def test_dump_omits_job_id_and_optional_empty_fields(self) -> None:
        article = Article("item", "Title", 100.0)

        dumped = article.dump()

        self.assertNotIn("job_id", dumped)
        self.assertNotIn("history", dumped)
        self.assertNotIn("hold_misses", dumped)


class ArticleLifecycleStateTests(unittest.TestCase):
    def _lifecycle(self) -> tuple[ArticleLifecycle, Stream, Stream, Stream]:
        active = Stream(Status.active)
        on_hold = Stream(Status.on_hold)
        finished = Stream(Status.finished)
        return (
            ArticleLifecycle(active, on_hold, finished, Article.create, 2),
            active,
            on_hold,
            finished,
        )

    def test_existing_active_article_update_reports_updated_not_new(self) -> None:
        lifecycle, active, _, _ = self._lifecycle()
        lifecycle.save({"identifier": "item", "title": "Old", "price": 100.0})

        article, is_new, is_updated = lifecycle.save(
            {"identifier": "item", "title": "Old", "price": 80.0}
        )

        self.assertFalse(is_new)
        self.assertTrue(is_updated)
        self.assertEqual(article, active.get_list()[0])
        self.assertEqual(active.get_list()[0].history[0].price, 100.0)

    def test_on_hold_article_reactivates_and_resets_hold_misses(self) -> None:
        lifecycle, active, on_hold, _ = self._lifecycle()
        lifecycle.save({"identifier": "item", "title": "Old", "price": 100.0})
        lifecycle.save(Article("item", "Old", 100.0), to_status=Status.on_hold)

        article, is_new, is_updated = lifecycle.save(
            {"identifier": "item", "title": "New", "price": 90.0}
        )

        assert article is not None
        self.assertFalse(is_new)
        self.assertTrue(is_updated)
        self.assertEqual(article.hold_misses, 0)
        self.assertEqual(len(on_hold), 0)
        self.assertEqual([item.identifier for item in active], ["item"])

    def test_finished_article_reactivates_and_records_status_history(self) -> None:
        lifecycle, active, _, finished = self._lifecycle()
        article = Article("item", "Old", 100.0)
        lifecycle.save(article, to_status=Status.finished)

        reactivated, is_new, is_updated = lifecycle.save(
            {"identifier": "item", "title": "Old", "price": 100.0}
        )

        assert reactivated is not None
        self.assertFalse(is_new)
        self.assertFalse(is_updated)
        self.assertEqual(len(finished), 0)
        self.assertEqual(len(active), 1)
        self.assertEqual(
            [history.status for history in reactivated.status_history],
            [Status.active, Status.finished],
        )

    def test_direct_finished_transition_clears_hold_misses(self) -> None:
        lifecycle, _, _, finished = self._lifecycle()
        article = Article("item", "Title", 100.0, hold_misses=3)

        lifecycle.save(article, to_status=Status.finished)

        self.assertEqual(finished.get_list()[0].hold_misses, 0)
        self.assertEqual(finished.get_list()[0].status_history[0].status, Status.finished)
