from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from scrapper import Scrapper
from scraper.motor import Motor
from scraper.status import Status


class DummyMotor(Motor):
    PAGE_DELAY_RANGE = (0.0, 0.0)
    FRESH_SESSION_PER_PAGE = False
    MAX_RATE_LIMIT_RETRIES = 1
    RATE_LIMIT_SLEEP_CAP = 1
    BLOCKED_BACKOFF_SECONDS = 0
    CONCURRENCY_LIMIT = 1

    def __init__(self, storage_path: str):
        super().__init__("test search", "https://example.com", storage_path=storage_path)

    def scrape_page(self, body: dict):
        return [], None


def make_item(identifier: str, title: str = "Item", price: float = 10.0) -> dict:
    return {
        "identifier": identifier,
        "title": title,
        "price": price,
        "url": f"https://example.com/{identifier}",
    }


class OnHoldLifecycleTests(unittest.TestCase):
    def test_active_missing_moves_to_on_hold_then_finished_after_three_misses(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            motor = DummyMotor(storage_path=str(Path(tmpdir) / "storage.json"))
            motor.save(make_item("A1", title="Alpha", price=10.0))

            motor._reconcile_missing([])
            self.assertEqual(len(motor.active), 0)
            self.assertEqual(len(motor.on_hold), 1)
            self.assertEqual(len(motor.finished), 0)

            hold_article = motor.on_hold.get_list()[0]
            self.assertEqual(hold_article.status, Status.on_hold)
            self.assertEqual(hold_article.hold_misses, 1)
            self.assertEqual(hold_article.status_history, [])

            motor._reconcile_missing([])
            motor._reconcile_missing([])

            self.assertEqual(len(motor.active), 0)
            self.assertEqual(len(motor.on_hold), 0)
            self.assertEqual(len(motor.finished), 1)

            finished_article = motor.finished.get_list()[0]
            self.assertEqual(finished_article.status, Status.finished)
            self.assertEqual(finished_article.hold_misses, 0)
            self.assertEqual(len(finished_article.status_history), 1)
            self.assertEqual(finished_article.status_history[0].status, Status.finished)

    def test_on_hold_reappears_before_threshold_returns_to_active_without_status_history(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            motor = DummyMotor(storage_path=str(Path(tmpdir) / "storage.json"))
            motor.save(make_item("B1", title="Beta", price=12.0))
            motor._reconcile_missing([])

            restored, _, _ = motor.save(make_item("B1", title="Beta", price=12.0))

            self.assertEqual(len(motor.active), 1)
            self.assertEqual(len(motor.on_hold), 0)
            self.assertEqual(len(motor.finished), 0)
            self.assertEqual(restored.status, Status.active)
            self.assertEqual(restored.hold_misses, 0)
            self.assertEqual(restored.status_history, [])

    def test_finished_reappears_records_lifecycle_marker(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            motor = DummyMotor(storage_path=str(Path(tmpdir) / "storage.json"))
            motor.save(make_item("C1", title="Gamma", price=20.0))
            motor._reconcile_missing([])
            motor._reconcile_missing([])
            motor._reconcile_missing([])

            restored, _, _ = motor.save(make_item("C1", title="Gamma", price=20.0))

            self.assertEqual(len(motor.active), 1)
            self.assertEqual(len(motor.on_hold), 0)
            self.assertEqual(len(motor.finished), 0)
            self.assertEqual(restored.status, Status.active)
            self.assertEqual(len(restored.status_history), 2)
            self.assertTrue(all(entry.status == Status.finished for entry in restored.status_history))

    def test_on_hold_state_round_trips_through_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            storage_path = Path(tmpdir) / "storage.json"
            motor = DummyMotor(storage_path=str(storage_path))
            motor.save(make_item("D1", title="Delta", price=30.0))
            motor._reconcile_missing([])
            asyncio.run(motor.save_to_file())

            reloaded = DummyMotor(storage_path=str(storage_path))
            self.assertEqual(len(reloaded.active), 0)
            self.assertEqual(len(reloaded.on_hold), 1)
            self.assertEqual(len(reloaded.finished), 0)

            article = reloaded.on_hold.get_list()[0]
            self.assertEqual(article.identifier, "D1")
            self.assertEqual(article.status, Status.on_hold)
            self.assertEqual(article.hold_misses, 1)

            payload = json.loads(storage_path.read_text(encoding="utf-8"))
            self.assertEqual(payload[0]["status"], Status.on_hold.value)
            self.assertEqual(payload[0]["hold_misses"], 1)

    def test_legacy_files_without_on_hold_still_load(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            storage_path = Path(tmpdir) / "storage.json"
            storage_path.write_text(
                json.dumps(
                    [
                        {
                            "identifier": "E1",
                            "title": "Active Item",
                            "price": 11.0,
                            "url": "https://example.com/E1",
                            "datetime": "2026-01-01 00:00:00",
                            "status": "active",
                        },
                        {
                            "identifier": "E2",
                            "title": "Finished Item",
                            "price": 22.0,
                            "url": "https://example.com/E2",
                            "datetime": "2026-01-01 00:00:00",
                            "status": "finished",
                        },
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            reloaded = DummyMotor(storage_path=str(storage_path))
            self.assertEqual(len(reloaded.active), 1)
            self.assertEqual(len(reloaded.on_hold), 0)
            self.assertEqual(len(reloaded.finished), 1)
            self.assertEqual(reloaded.active.get_list()[0].status, Status.active)
            self.assertEqual(reloaded.finished.get_list()[0].status, Status.finished)

    def test_public_list_source_returns_only_active_elements(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            motor = DummyMotor(storage_path=str(Path(tmpdir) / "storage.json"))
            motor.save(make_item("F1", title="Visible", price=40.0))
            motor.save(make_item("F2", title="Hidden", price=41.0), to_status=Status.on_hold)
            motor.save(make_item("F3", title="Gone", price=42.0), to_status=Status.finished)

            scrapper = Scrapper()
            scrapper.motors = [motor]

            payload = scrapper.get_list()
            self.assertEqual(len(payload), 1)
            self.assertEqual(payload[0]["title"], "test search")
            self.assertEqual(len(payload[0]["elements"]), 1)
            self.assertEqual(payload[0]["elements"][0]["identifier"], "F1")


if __name__ == "__main__":
    unittest.main()
