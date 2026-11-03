"""On-demand URL preview generation backed by a provider previewer registry."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from provider.amazon.urls import preview_amazon_url
from provider.liverpool.urls import preview_liverpool_url
from provider.mercado_libre.urls import preview_mercado_libre_url
from provider.palacio_de_hierro.urls import preview_palacio_url
from scraper.jobs.loader import DEFAULT_CONFIG_PATH, load_jobs

UrlPreviewer = Callable[[dict[str, Any]], str]
_URL_PREVIEWERS: dict[str, UrlPreviewer] = {}


def register_url_previewer(provider: str, previewer: UrlPreviewer) -> None:
    """Register a URL preview callable for ``provider`` (Open/Closed extension point)."""
    key = provider.strip()
    if not key:
        raise ValueError("Provider key cannot be blank.")
    _URL_PREVIEWERS[key] = previewer


def supported_preview_providers() -> tuple[str, ...]:
    """Return the registered provider keys supporting URL preview."""
    return tuple(_URL_PREVIEWERS.keys())


register_url_previewer(
    "ml",
    lambda job: preview_mercado_libre_url(
        query=job.get("query"),
        seller=job.get("seller"),
        category=job.get("category"),
        state=job.get("state"),
        url=job.get("url"),
    ),
)
register_url_previewer(
    "az",
    lambda job: preview_amazon_url(
        query=job.get("query"),
        seller=job.get("seller"),
        brand=job.get("brand"),
        url=job.get("url"),
    ),
)
register_url_previewer(
    "lv",
    lambda job: preview_liverpool_url(
        query=job.get("query"),
        page=job.get("page"),
        category=job.get("category"),
        brand=job.get("brand"),
        talla=job.get("talla"),
        url=job.get("url"),
    ),
)
register_url_previewer(
    "ph",
    lambda job: preview_palacio_url(
        query=job.get("query"),
        page=job.get("page"),
        brands=job.get("brands"),
        url=job.get("url"),
    ),
)


def preview_job_url(
    job_id: str, *, provider: str, config_path: Path | str = DEFAULT_CONFIG_PATH
) -> str:
    """Generate one provider URL on demand from a configured job entry.

    Args:
        job_id: Provider-local job identifier from ``config/jobs.yaml``.
        provider: Registered provider key (e.g. ``ml``, ``az``, ``lv``, ``ph``).
        config_path: Optional jobs YAML path override.

    Returns:
        The generated or explicit URL for the matching job.

    Raises:
        ValueError: If provider/job match is missing, not unique, or unsupported.
    """
    previewer = _URL_PREVIEWERS.get(provider)
    if previewer is None:
        valid = ", ".join(supported_preview_providers())
        raise ValueError(f"Unknown provider. Valid values: {valid}.")

    entries = load_jobs(config_path)
    matches = [
        entry
        for entry in entries
        if entry.get("provider") == provider and entry.get("job_id") == job_id
    ]
    if not matches:
        raise ValueError(f"No job found for provider={provider!r} and job_id={job_id!r}.")
    if len(matches) > 1:
        raise ValueError(f"Multiple jobs found for provider={provider!r} and job_id={job_id!r}.")

    return previewer(matches[0])
