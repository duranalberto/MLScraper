from __future__ import annotations

import logging
from pathlib import Path

from shared.scraping.motor import Motor

from .factories import register_default_factories
from .loader import DEFAULT_CONFIG_PATH, load_jobs
from .registry import _REGISTRY, build_motors, register_entries

logger = logging.getLogger(__name__)
_FACTORIES_REGISTERED = False


def _ensure_default_factories_registered() -> None:
    global _FACTORIES_REGISTERED
    if _FACTORIES_REGISTERED:
        return
    register_default_factories(_REGISTRY)
    _FACTORIES_REGISTERED = True


def get_motors(config_path: Path | str = DEFAULT_CONFIG_PATH) -> list[Motor]:
    _ensure_default_factories_registered()

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
