"""Provider and orchestrator health state calculation."""

from __future__ import annotations

from collections import Counter
from typing import Any


def initial_health(motor_count: int) -> dict[str, Any]:
    return {
        "status": "starting",
        "last_cycle_finished_at": None,
        "last_cycle_duration_s": None,
        "motor_count": motor_count,
        "providers": {},
    }


def ensure_provider_cycle_health(
    provider_cycle_health: dict[str, dict[str, Any]],
    provider: str,
) -> dict[str, Any]:
    return provider_cycle_health.setdefault(
        provider,
        {
            "status": "idle",
            "last_cycle_started_at": None,
            "last_cycle_finished_at": None,
            "last_cycle_duration_s": None,
            "cycle_count": 0,
            "last_error": None,
        },
    )


def refresh_provider_health(
    *,
    health: dict[str, Any],
    motors: list[Any],
    provider_limits: dict[str, int],
    provider_active: Counter[str],
    provider_waiting: Counter[str],
    provider_job_counts: Counter[str],
    provider_cycle_health: dict[str, dict[str, Any]],
    default_provider_concurrency: int,
) -> None:
    """Update ``health['providers']`` in a single $O(M + P \\log P)$ pass."""
    providers = set(provider_job_counts)
    providers.update(provider_limits)
    providers.update(provider_active)
    providers.update(provider_waiting)
    providers.update(provider_cycle_health)

    blocked_counts: Counter[str] = Counter()
    reasons_by_provider: dict[str, set[str]] = {}
    for motor in motors:
        reason = getattr(motor, "blocked_reason", None)
        if reason:
            provider_key = motor.provider_key
            blocked_counts[provider_key] += 1
            reasons_by_provider.setdefault(provider_key, set()).add(str(reason))

    health["providers"] = {
        provider: {
            **ensure_provider_cycle_health(provider_cycle_health, provider),
            "configured_limit": provider_limits.get(provider, default_provider_concurrency),
            "job_count": provider_job_counts.get(provider, 0),
            "active_jobs": max(0, provider_active.get(provider, 0)),
            "queued_jobs": max(0, provider_waiting.get(provider, 0)),
            "blocked_jobs": blocked_counts.get(provider, 0),
            "block_reasons": sorted(reasons_by_provider.get(provider, ())),
        }
        for provider in sorted(providers)
    }
