"""
provider/generator.py

Scraping Job Catalogue — YAML-driven
──────────────────────────────────────
All scraping jobs are declared in ``config/jobs.yaml``.  This module
loads that file, coerces enum fields, and materialises Motor instances
via the registry.

How to add or remove a job
──────────────────────────
Edit ``config/jobs.yaml``.  No Python file needs to change.

How to add a new provider
─────────────────────────
1. Implement the Motor subclass.
2. Register its factory in provider/factories.py.
3. Add entries to config/jobs.yaml using the new provider key.

Overriding the config path
──────────────────────────
Pass a different path to ``get_motors()``, e.g. for tests:

    motors = get_motors(config_path="tests/fixtures/jobs.yaml")
"""

from __future__ import annotations

import logging
from pathlib import Path

# Factories must be imported so their @_REGISTRY.factory decorators run.
import provider.factories  # noqa: F401  (side-effect import)

from provider.loader import load_jobs, DEFAULT_CONFIG_PATH
from provider.registry import register_entries, build_motors
from scraper.motor import Motor

logger = logging.getLogger(__name__)


def get_motors(config_path: Path | str = DEFAULT_CONFIG_PATH) -> list[Motor]:
    """
    Load job entries from *config_path* and materialise every entry
    into a Motor instance.

    Parameters
    ----------
    config_path:
        Path to the YAML jobs file.  Defaults to ``config/jobs.yaml``.

    Returns
    -------
    list[Motor]
        One Motor per valid job entry.  Invalid entries are skipped and
        logged by the loader / registry.
    """
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

    register_entries(entries)
    return build_motors()