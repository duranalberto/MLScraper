"""
scraper/jobs/loader.py

YAML Job Catalogue Loader
─────────────────────────
Loads scraping job entries from a YAML file and coerces provider-specific
string values (category names, seller names) into their proper enum types.

Design decisions
────────────────
• The YAML file uses plain strings for enum fields ("amazon_mx", "consolas")
  so the file stays human-readable without importing Python enums.
  Coercion happens here, once, at load time.

• All validation errors are reported together (not short-circuited) so
  a misconfigured file surfaces every problem in one pass.

• Unknown keys are passed through untouched — the factory layer decides
  which kwargs it actually uses.

• The loader is intentionally free of Motor/factory imports to keep the
  dependency direction clean: loader → enums only.

Edge cases handled
──────────────────
• Missing or empty YAML file               → returns [] with a warning
• File not found                           → FileNotFoundError with clear message
• Malformed YAML syntax                    → YAMLError with file + line info
• `jobs` key missing or not a list         → ValueError
• Entry is not a dict                      → entry skipped with a warning
• Entry missing required `provider` key   → entry skipped with a warning
• Unknown category / seller string        → entry skipped with a warning
• `search_term` is missing or blank        → entry skipped with a warning
• `url` required for lv/ph but absent     → entry skipped with a warning
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from provider.amazon.options import Seller
from provider.mercado_libre.options import Category

logger = logging.getLogger(__name__)

_URL_REQUIRED_PROVIDERS = {"lv", "ph"}

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = _REPO_ROOT / "config" / "jobs.yaml"


def _coerce_category(raw: str, entry: dict) -> Category | None:
    """Convert a category string to a Category enum member, or return None on error."""
    try:
        return Category[raw]
    except KeyError:
        valid = [m.name for m in Category]
        logger.warning(
            "Unknown category %r in entry %r. Valid values: %s",
            raw,
            entry,
            valid,
        )
        return None


def _coerce_seller(raw: str, entry: dict) -> Seller | None:
    """Convert a seller string to a Seller enum member, or return None on error."""
    try:
        return Seller[raw]
    except KeyError:
        valid = [m.name for m in Seller]
        logger.warning(
            "Unknown seller %r in entry %r. Valid values: %s",
            raw,
            entry,
            valid,
        )
        return None


def _validate_and_coerce(entry: Any, index: int) -> dict | None:
    """
    Validate a single raw YAML entry and coerce enum strings.
    Returns a clean dict ready for the registry, or None if the entry is invalid.
    """
    if not isinstance(entry, dict):
        logger.warning("Job #%d is not a mapping — skipped: %r", index, entry)
        return None

    provider = entry.get("provider")
    if not provider or not isinstance(provider, str):
        logger.warning("Job #%d is missing a valid 'provider' key — skipped: %r", index, entry)
        return None

    search_term = entry.get("search_term")
    if not search_term or not str(search_term).strip():
        logger.warning(
            "Job #%d (provider=%r) is missing a non-blank 'search_term' — skipped.",
            index,
            provider,
        )
        return None

    if provider in _URL_REQUIRED_PROVIDERS and not entry.get("url"):
        logger.warning(
            "Job #%d (provider=%r, search_term=%r) requires a 'url' field — skipped.",
            index,
            provider,
            search_term,
        )
        return None

    clean: dict = dict(entry)

    if "category" in clean:
        coerced = _coerce_category(str(clean["category"]), entry)
        if coerced is None:
            return None
        clean["category"] = coerced

    # Coerce `seller` string → Seller enum
    if "seller" in clean:
        coerced = _coerce_seller(str(clean["seller"]), entry)
        if coerced is None:
            return None
        clean["seller"] = coerced

    # Normalise search_term to str (YAML may parse numeric-looking values as int)
    clean["search_term"] = str(search_term).strip()

    return clean


def load_jobs(config_path: Path | str = DEFAULT_CONFIG_PATH) -> list[dict]:
    """
    Load and validate scraping job entries from a YAML file.

    Parameters
    ----------
    config_path:
        Path to the YAML file (default: ``config/jobs.yaml``).

    Returns
    -------
    list[dict]
        A list of validated, coerced entry dicts ready to pass to the registry.

    Raises
    ------
    FileNotFoundError
        If *config_path* does not exist.
    ValueError
        If the YAML document is structurally invalid (no `jobs` list).
    yaml.YAMLError
        If the file cannot be parsed as valid YAML.
    """
    path = Path(config_path)

    if not path.exists():
        raise FileNotFoundError(
            f"Jobs config file not found: '{path.resolve()}'. "
            "Create the file or pass a different path to load_jobs()."
        )

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise yaml.YAMLError(f"Failed to parse YAML from '{path}': {exc}") from exc

    if raw is None:
        logger.warning("'%s' is empty — no jobs loaded.", path)
        return []

    if not isinstance(raw, dict) or "jobs" not in raw:
        raise ValueError(
            f"'{path}' must contain a top-level 'jobs' key with a list of job entries."
        )

    jobs_raw = raw["jobs"]

    if jobs_raw is None:
        logger.warning("'jobs' key in '%s' is empty — no jobs loaded.", path)
        return []

    if not isinstance(jobs_raw, list):
        raise ValueError(f"'jobs' in '{path}' must be a list, got {type(jobs_raw).__name__}.")

    entries: list[dict] = []
    for index, raw_entry in enumerate(jobs_raw, start=1):
        clean = _validate_and_coerce(raw_entry, index)
        if clean is not None:
            entries.append(clean)

    loaded = len(entries)
    skipped = len(jobs_raw) - loaded
    logger.info(
        "Loaded %d job(s) from '%s'%s.",
        loaded,
        path,
        f" ({skipped} skipped due to errors)" if skipped else "",
    )

    return entries
