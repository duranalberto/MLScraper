"""
scraper/jobs/loader.py

YAML Job Catalogue Loader
─────────────────────────
Loads scraping job entries from a YAML file and coerces provider-specific
string values (category, seller, and Liverpool page names) into their proper
enum types.

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
• Unknown provider-specific enum string   → entry skipped with a warning
• `search_term` is missing or blank        → entry skipped with a warning
• `url` required for ph but absent        → entry skipped with a warning
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from provider.amazon.options import Seller as AmazonSeller
from provider.liverpool.options import Page as LiverpoolPage
from provider.liverpool.options import resolve_page
from provider.mercado_libre.options import Category as MercadoLibreCategory

logger = logging.getLogger(__name__)

_URL_REQUIRED_PROVIDERS = {"ph"}

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = _REPO_ROOT / "config" / "jobs.yaml"


def _coerce_enum(raw: str, entry: dict, enum_type, field_name: str):
    """Convert a YAML string to a provider enum member, or return None on error."""
    try:
        return enum_type[raw]
    except KeyError:
        valid = [m.name for m in enum_type]
        logger.warning(
            "Unknown %s %r in entry %r. Valid values: %s",
            field_name,
            raw,
            entry,
            valid,
        )
        return None


def _coerce_liverpool_page(raw: str, entry: dict, field_name: str) -> LiverpoolPage | None:
    """Convert a Liverpool page string to a Page enum member, or return None."""
    try:
        return resolve_page(raw)
    except ValueError as exc:
        logger.warning(
            "Unknown %s %r in entry %r. %s",
            field_name,
            raw,
            entry,
            exc,
        )
        return None


def _coerce_provider_fields(clean: dict, entry: dict) -> dict | None:
    """Coerce provider-owned YAML fields without creating shared filter inputs."""
    provider = clean["provider"]

    if "category" in clean:
        if provider == "ml":
            coerced = _coerce_enum(str(clean["category"]), entry, MercadoLibreCategory, "category")
            if coerced is None:
                return None
            clean["category"] = coerced

    if provider == "lv":
        page_value = None
        if "page" in clean:
            page_value = _coerce_liverpool_page(str(clean["page"]), entry, "page")
            if page_value is None:
                return None
            clean["page"] = page_value

        if "category" in clean:
            category_value = _coerce_liverpool_page(str(clean["category"]), entry, "category")
            if category_value is None:
                return None
            if page_value is not None and page_value != category_value:
                logger.warning(
                    "Liverpool entry %r has conflicting 'page' and legacy 'category' values.",
                    entry,
                )
                return None
            clean["page"] = category_value
            clean.pop("category", None)

    if "seller" in clean:
        if provider == "az":
            coerced = _coerce_enum(str(clean["seller"]), entry, AmazonSeller, "seller")
            if coerced is None:
                return None
            clean["seller"] = coerced
        elif provider == "lv":
            clean.pop("seller")
            logger.warning(
                "Liverpool job %r includes unsupported 'seller'; generated Liverpool URLs "
                "always filter to Liverpool seller. Use explicit 'url' for custom sellers.",
                clean["search_term"],
            )

    return clean


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

    # Normalise search_term to str (YAML may parse numeric-looking values as int)
    clean["search_term"] = str(search_term).strip()

    return _coerce_provider_fields(clean, entry)


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
