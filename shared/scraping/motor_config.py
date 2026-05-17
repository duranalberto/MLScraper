from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Tuple

import yaml

CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "motors.yaml"


@lru_cache(maxsize=1)
def load_motor_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(
            f"Motor config file not found: '{CONFIG_PATH.resolve()}'. "
            "Create config/motors.yaml to define scraper policy values."
        )

    with CONFIG_PATH.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}

    if not isinstance(data, dict):
        raise ValueError(f"'{CONFIG_PATH}' must contain a YAML mapping at the top level.")

    return data


def apply_motor_config(motor: Any) -> None:
    config = load_motor_config()
    class_config = lookup_class_config(config, type(motor).__name__)

    motor.PAGE_DELAY_RANGE = coerce_page_delay(get_setting(motor, "PAGE_DELAY_RANGE", class_config))
    motor.FRESH_SESSION_PER_PAGE = coerce_bool(
        get_setting(motor, "FRESH_SESSION_PER_PAGE", class_config)
    )
    motor.MAX_RATE_LIMIT_RETRIES = coerce_int(
        get_setting(motor, "MAX_RATE_LIMIT_RETRIES", class_config)
    )
    motor.RATE_LIMIT_SLEEP_CAP = coerce_int(
        get_setting(motor, "RATE_LIMIT_SLEEP_CAP", class_config)
    )
    motor.BLOCKED_BACKOFF_SECONDS = coerce_int(
        get_setting(motor, "BLOCKED_BACKOFF_SECONDS", class_config)
    )
    motor.CONCURRENCY_LIMIT = coerce_int(get_setting(motor, "CONCURRENCY_LIMIT", class_config))
    motor.FETCH_STRATEGY = coerce_fetch_strategy(get_setting(motor, "FETCH_STRATEGY", class_config))
    motor.FETCH_TIMEOUT_SECONDS = coerce_int(
        get_setting(motor, "FETCH_TIMEOUT_SECONDS", class_config)
    )
    motor.BROWSER_WAIT_SELECTOR = coerce_optional_str(
        get_setting(motor, "BROWSER_WAIT_SELECTOR", class_config)
    )
    motor.BROWSER_BLOCK_SELECTORS = coerce_string_tuple(
        get_setting(motor, "BROWSER_BLOCK_SELECTORS", class_config)
    )


def lookup_class_config(config: dict[str, Any], class_name: str) -> dict[str, Any]:
    defaults = config.get("defaults", {})
    if defaults and not isinstance(defaults, dict):
        raise ValueError("config/motors.yaml 'defaults' must be a mapping.")

    keys = [class_name, f"providers.{class_name}"]
    motor_config: dict[str, Any] = {}
    for key in keys:
        value = config
        for part in key.split("."):
            if not isinstance(value, dict) or part not in value:
                value = None
                break
            value = value[part]
        if isinstance(value, dict):
            motor_config = value
            break

    merged = dict(defaults or {})
    merged.update(motor_config)
    return merged


def get_setting(motor: Any, key: str, class_config: dict[str, Any]) -> Any:
    subclass_value = type(motor).__dict__.get(key, None)
    if subclass_value is not None:
        return subclass_value

    if key in class_config:
        return class_config[key]

    raise KeyError(
        f"Missing motor setting '{key}' for {type(motor).__name__}. "
        f"Add it to '{CONFIG_PATH}' or override it in the implementation."
    )


def coerce_page_delay(value: Any) -> Tuple[float, float]:
    if isinstance(value, (list, tuple)) and len(value) == 2:
        return float(value[0]), float(value[1])
    raise ValueError(f"PAGE_DELAY_RANGE must be a 2-item list or tuple, got {value!r}.")


def coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    raise ValueError(f"Expected a boolean value, got {value!r}.")


def coerce_int(value: Any) -> int:
    if isinstance(value, bool) or value is None:
        raise ValueError(f"Expected an integer value, got {value!r}.")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Expected an integer value, got {value!r}.") from exc


def coerce_fetch_strategy(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError(f"FETCH_STRATEGY must be a string, got {value!r}.")
    strategy = value.strip().lower()
    if strategy not in {"aiohttp", "browser"}:
        raise ValueError(f"FETCH_STRATEGY must be one of 'aiohttp' or 'browser', got {value!r}.")
    return strategy


def coerce_optional_str(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"Expected a string or null value, got {value!r}.")
    value = value.strip()
    return value or None


def coerce_string_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        value = [value]
    if isinstance(value, (list, tuple)):
        return tuple(str(item).strip() for item in value if str(item).strip())
    raise ValueError(f"Expected a string list value, got {value!r}.")
