from __future__ import annotations

import logging
from pathlib import Path

import provider.factories

from provider.loader import load_jobs, DEFAULT_CONFIG_PATH
from provider.registry import _REGISTRY, register_entries, build_motors
from scraper.motor import Motor

logger = logging.getLogger(__name__)


def get_motors(config_path: Path | str = DEFAULT_CONFIG_PATH) -> list[Motor]:
    try:
        entries = load_jobs(config_path)
    except FileNotFoundError as exc:
        logger.error("%s — returning empty motor list.", exc)
        return []
    except Exception as exc:
        logger.error("Unexpected error loading jobs from '%s': %s", config_path, exc)
        return []

    if not entries:
        logger.warning("No job entries were loaded from '%s'.", config_path)
        return []

    _REGISTRY.clear_entries()
    register_entries(entries)
    return build_motors()