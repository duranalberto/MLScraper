from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scraper.runtime.config import RuntimeConfig, load_runtime_config
from shared.scraping import motor_config


class RuntimeConfigTests(unittest.TestCase):
    def test_load_runtime_config_reads_required_backoff_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "scrapper.yaml"
            path.write_text("BACKOFF_INITIAL: 5\nBACKOFF_MAX: 30\n", encoding="utf-8")

            config = load_runtime_config.__wrapped__(path)

        self.assertEqual(config, RuntimeConfig(backoff_initial=5, backoff_max=30))

    def test_load_runtime_config_rejects_missing_required_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "scrapper.yaml"
            path.write_text("BACKOFF_INITIAL: 5\n", encoding="utf-8")

            with self.assertRaisesRegex(KeyError, "BACKOFF_MAX"):
                load_runtime_config.__wrapped__(path)

    def test_load_runtime_config_rejects_non_mapping_yaml(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "scrapper.yaml"
            path.write_text("- nope\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "YAML mapping"):
                load_runtime_config.__wrapped__(path)


class MotorConfigTests(unittest.TestCase):
    def test_lookup_class_config_merges_defaults_with_direct_provider_override(self) -> None:
        config = {
            "defaults": {"FETCH_STRATEGY": "aiohttp", "CONCURRENCY_LIMIT": 2},
            "Amazon": {"CONCURRENCY_LIMIT": 1},
        }

        self.assertEqual(
            motor_config.lookup_class_config(config, "Amazon"),
            {"FETCH_STRATEGY": "aiohttp", "CONCURRENCY_LIMIT": 1},
        )

    def test_lookup_class_config_supports_nested_providers_mapping(self) -> None:
        config = {
            "defaults": {"FETCH_STRATEGY": "aiohttp", "CONCURRENCY_LIMIT": 2},
            "providers": {"MercadoLibre": {"FETCH_STRATEGY": "browser"}},
        }

        self.assertEqual(
            motor_config.lookup_class_config(config, "MercadoLibre"),
            {"FETCH_STRATEGY": "browser", "CONCURRENCY_LIMIT": 2},
        )

    def test_get_setting_prefers_subclass_override_before_yaml_config(self) -> None:
        class DummyMotor:
            FETCH_STRATEGY = "browser"

        value = motor_config.get_setting(
            DummyMotor(),
            "FETCH_STRATEGY",
            {"FETCH_STRATEGY": "aiohttp"},
        )

        self.assertEqual(value, "browser")

    def test_get_setting_reports_missing_required_motor_setting(self) -> None:
        with self.assertRaisesRegex(KeyError, "Missing motor setting 'FETCH_STRATEGY'"):
            motor_config.get_setting(SimpleNamespace(), "FETCH_STRATEGY", {})

    def test_apply_motor_config_coerces_all_supported_values(self) -> None:
        config = {
            "defaults": {
                "PAGE_DELAY_RANGE": [0, 0],
                "FRESH_SESSION_PER_PAGE": False,
                "MAX_RATE_LIMIT_RETRIES": "4",
                "RATE_LIMIT_SLEEP_CAP": 90,
                "BLOCKED_BACKOFF_SECONDS": 10,
                "CONCURRENCY_LIMIT": 2,
                "FETCH_STRATEGY": "BROWSER",
                "FETCH_TIMEOUT_SECONDS": 30,
                "BROWSER_WAIT_SELECTOR": "  section.results  ",
                "BROWSER_BLOCK_SELECTORS": [" body.blocked ", "", "url*=gate"],
            }
        }
        motor = SimpleNamespace()

        with patch("shared.scraping.motor_config.load_motor_config", return_value=config):
            motor_config.apply_motor_config(motor)

        self.assertEqual(motor.PAGE_DELAY_RANGE, (0.0, 0.0))
        self.assertEqual(motor.MAX_RATE_LIMIT_RETRIES, 4)
        self.assertEqual(motor.FETCH_STRATEGY, "browser")
        self.assertEqual(motor.BROWSER_WAIT_SELECTOR, "section.results")
        self.assertEqual(motor.BROWSER_BLOCK_SELECTORS, ("body.blocked", "url*=gate"))

    def test_coercers_reject_invalid_values(self) -> None:
        invalid_calls = [
            lambda: motor_config.coerce_bool("true"),
            lambda: motor_config.coerce_int(True),
            lambda: motor_config.coerce_page_delay([1]),
            lambda: motor_config.coerce_fetch_strategy("spaceship"),
            lambda: motor_config.coerce_optional_str(123),
            lambda: motor_config.coerce_string_tuple(123),
        ]

        for call in invalid_calls:
            with self.subTest(call=call):
                with self.assertRaises(ValueError):
                    call()
