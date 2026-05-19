from __future__ import annotations

import asyncio
import json
import unittest
from unittest.mock import AsyncMock, patch

from shared.articles.article import Article
from shared.articles.repository import ArticleRepository
from shared.articles.status import Status
from shared.articles.stream import Stream
from tests.helpers import PatchedDataPath
from utils import file_manager


class FileManagerTests(unittest.TestCase):
    def test_resolve_rejects_relative_parent_traversal(self) -> None:
        with self.assertRaisesRegex(ValueError, "Parent-directory traversal"):
            file_manager._resolve("../outside.json")

    def test_resolve_rejects_absolute_paths_outside_data_root(self) -> None:
        with PatchedDataPath():
            with self.assertRaisesRegex(ValueError, "Absolute paths must stay under DATA_PATH"):
                file_manager._resolve("/tmp/outside-mlscraper.json")

    def test_write_creates_nested_file_and_backup(self) -> None:
        with PatchedDataPath() as data_root:
            file_manager.write_in_file_sync("provider/items.json", '[{"identifier": "one"}]')
            file_manager.write_in_file_sync("provider/items.json", '[{"identifier": "two"}]')

            target = data_root / "provider" / "items.json"
            backup = data_root / "provider" / "items.json.bak"
            self.assertEqual(json.loads(target.read_text(encoding="utf-8"))[0]["identifier"], "two")
            self.assertEqual(json.loads(backup.read_text(encoding="utf-8"))[0]["identifier"], "one")

    def test_read_recovers_from_backup_when_primary_json_is_invalid(self) -> None:
        with PatchedDataPath() as data_root:
            target = data_root / "provider" / "items.json"
            target.parent.mkdir(parents=True)
            target.write_text("{invalid", encoding="utf-8")
            target.with_name("items.json.bak").write_text(
                '[{"identifier": "one"}]', encoding="utf-8"
            )

            self.assertEqual(
                file_manager.read_json_file("provider/items.json"), [{"identifier": "one"}]
            )

    def test_read_returns_empty_list_for_non_list_json_without_backup(self) -> None:
        with PatchedDataPath() as data_root:
            target = data_root / "provider" / "items.json"
            target.parent.mkdir(parents=True)
            target.write_text('{"identifier": "one"}', encoding="utf-8")

            self.assertEqual(file_manager.read_json_file("provider/items.json"), [])

    def test_async_write_delegates_to_sync_writer(self) -> None:
        with patch("utils.file_manager.write_in_file_sync") as write_sync:
            asyncio.run(file_manager.write_in_file("provider/items.json", "[]"))

        write_sync.assert_called_once_with("provider/items.json", "[]")


class ArticleRepositoryTests(unittest.TestCase):
    def _repository(self) -> tuple[ArticleRepository, Stream, Stream, Stream]:
        active = Stream(Status.active)
        on_hold = Stream(Status.on_hold)
        finished = Stream(Status.finished)
        return (
            ArticleRepository(
                "provider/items.json", active, on_hold, finished, Article.create, debug=False
            ),
            active,
            on_hold,
            finished,
        )

    def test_load_routes_statuses_and_normalizes_hold_misses(self) -> None:
        records = [
            {"identifier": "active", "title": "Active", "price": 10},
            {"identifier": "hold", "title": "Hold", "price": 20, "status": "on_hold"},
            {
                "identifier": "done",
                "title": "Done",
                "price": 30,
                "status": "finished",
                "hold_misses": 9,
            },
        ]
        repository, active, on_hold, finished = self._repository()

        with patch("shared.articles.repository.read_json_file", return_value=records):
            repository.load()

        self.assertEqual([article.identifier for article in active], ["active"])
        self.assertEqual([article.identifier for article in on_hold], ["hold"])
        self.assertEqual(on_hold.get_list()[0].hold_misses, 1)
        self.assertEqual([article.identifier for article in finished], ["done"])
        self.assertEqual(finished.get_list()[0].hold_misses, 0)

    def test_load_skips_malformed_and_duplicate_records(self) -> None:
        records = [
            ["not", "a", "dict"],
            {"identifier": "", "title": "Missing", "price": 1},
            {"identifier": "dup", "title": "First", "price": 1},
            {"identifier": "dup", "title": "Second", "price": 2},
            {"identifier": "bad", "title": "No price"},
        ]
        repository, active, on_hold, finished = self._repository()

        with patch("shared.articles.repository.read_json_file", return_value=records):
            repository.load()

        self.assertEqual([article.identifier for article in active], ["dup"])
        self.assertEqual(len(on_hold), 0)
        self.assertEqual(len(finished), 0)

    def test_save_orders_streams_and_writes_dump(self) -> None:
        repository, active, on_hold, finished = self._repository()
        older = Article("old", "Old", 1, datetime="2024-01-01")
        newer = Article("new", "New", 2, datetime="2025-01-01")
        active.add(older)
        active.add(newer)

        with patch("shared.articles.repository.write_in_file", new=AsyncMock()) as write:
            asyncio.run(repository.save([older, newer]))

        self.assertEqual([article.identifier for article in active], ["new", "old"])
        call = write.await_args
        assert call is not None
        written = call.args[1]
        self.assertNotIn("search_term", written)
        self.assertIn('"identifier": "old"', written)
