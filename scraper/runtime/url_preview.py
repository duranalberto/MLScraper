from __future__ import annotations

from pathlib import Path

from provider.amazon.urls import preview_amazon_url
from provider.liverpool.urls import preview_liverpool_url
from provider.mercado_libre.urls import preview_mercado_libre_url
from provider.palacio_de_hierro.urls import preview_palacio_url
from scraper.jobs.loader import DEFAULT_CONFIG_PATH, load_jobs


def preview_job_url(
    job_id: str, *, provider: str, config_path: Path | str = DEFAULT_CONFIG_PATH
) -> str:
    """Generate one provider URL on demand from a configured job entry.

    Args:
        job_id: Provider-local job identifier from ``config/jobs.yaml``.
        provider: Provider key (``ml``, ``az``, ``lv``, ``ph``).
        config_path: Optional jobs YAML path override.

    Returns:
        The generated or explicit URL for the matching job.

    Raises:
        ValueError: If provider/job match is missing or not unique.
    """
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

    job = matches[0]
    if provider == "ml":
        return preview_mercado_libre_url(
            query=job.get("query"),
            seller=job.get("seller"),
            category=job.get("category"),
            state=job.get("state"),
            url=job.get("url"),
        )
    if provider == "az":
        return preview_amazon_url(
            query=job.get("query"),
            seller=job.get("seller"),
            brand=job.get("brand"),
            url=job.get("url"),
        )
    if provider == "lv":
        return preview_liverpool_url(
            query=job.get("query"),
            page=job.get("page"),
            category=job.get("category"),
            brand=job.get("brand"),
            talla=job.get("talla"),
            url=job.get("url"),
        )
    if provider == "ph":
        return preview_palacio_url(
            query=job.get("query"),
            page=job.get("page"),
            brands=job.get("brands"),
            url=job.get("url"),
        )
    raise ValueError("Unknown provider. Valid values: ml, az, lv, ph.")
