from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable

DEFAULT_PROVIDER_CONCURRENCY = 1


def configured_provider_limit(
    *,
    provider_limits: dict[str, int],
    provider: str,
    limit: int | None,
    default_provider_concurrency: int = DEFAULT_PROVIDER_CONCURRENCY,
    logger: logging.Logger,
) -> int:
    existing = provider_limits.get(provider)
    if limit is None:
        limit = default_provider_concurrency
    elif limit < 1:
        if existing is None:
            logger.warning(
                "Provider '%s' requested invalid concurrency %d; clamping to 1.",
                provider,
                limit,
            )
        limit = 1

    if existing is None:
        provider_limits[provider] = limit
    elif existing != limit:
        logger.warning(
            "Provider '%s' requested concurrency %d but already has %d; keeping the first configured value.",
            provider,
            limit,
            existing,
        )
        limit = existing
    return limit


def get_provider_semaphore(
    *,
    provider_semaphores: dict[str, asyncio.Semaphore],
    provider_limits: dict[str, int],
    provider: str,
    limit: int | None,
    default_provider_concurrency: int = DEFAULT_PROVIDER_CONCURRENCY,
    logger: logging.Logger,
    refresh_provider_health: Callable[[], None],
) -> asyncio.Semaphore:
    limit = configured_provider_limit(
        provider_limits=provider_limits,
        provider=provider,
        limit=limit,
        default_provider_concurrency=default_provider_concurrency,
        logger=logger,
    )

    semaphore = provider_semaphores.get(provider)
    if semaphore is None:
        provider_semaphores[provider] = asyncio.Semaphore(limit)
        refresh_provider_health()
    return provider_semaphores[provider]


async def scrape_with_limit(
    *,
    motor: Any,
    get_semaphore: Callable[[str, int | None], asyncio.Semaphore],
    provider_active: Any,
    provider_waiting: Any,
    refresh_provider_health: Callable[[], None],
    broadcast: Callable[..., Awaitable[None]],
    logger: logging.Logger,
) -> None:
    provider = motor.provider_key
    semaphore = get_semaphore(provider, motor.CONCURRENCY_LIMIT)
    acquired = False
    provider_waiting[provider] += 1
    refresh_provider_health()
    try:
        async with semaphore:
            acquired = True
            provider_waiting[provider] -= 1
            provider_active[provider] += 1
            refresh_provider_health()
            try:
                await motor.scrape(caller=broadcast, silent=True)
            finally:
                provider_active[provider] -= 1
                refresh_provider_health()
    except Exception:
        logger.exception(
            "Motor '%s' (%s) failed during scrape; continuing with the remaining motors.",
            motor.job_id,
            provider,
        )
    finally:
        if not acquired:
            provider_waiting[provider] -= 1
        refresh_provider_health()
