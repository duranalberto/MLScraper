"""
Orchestrator — runs all motors on a schedule and routes notification events.
"""

import asyncio
import logging
from collections import Counter
from time import gmtime, strftime, time
from typing import Any

from scraper.jobs.generator import get_motors
from scraper.runtime.config import RuntimeConfig, load_runtime_config
from scraper.runtime.provider_health import (
    ensure_provider_cycle_health,
    initial_health,
    refresh_provider_health,
)
from scraper.runtime.provider_runtime import (
    DEFAULT_PROVIDER_CONCURRENCY,
    configured_provider_limit,
    get_provider_semaphore,
    scrape_with_limit,
)
from scraper.runtime.telegram_notifications import TelegramNotifier
from shared.scraping.motor import Motor

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


class Scrapper:
    def __init__(
        self,
        *,
        runtime_config: RuntimeConfig | None = None,
        notifier: TelegramNotifier | None = None,
        motors: list[Motor] | None = None,
    ) -> None:
        self.runtime_config = runtime_config or load_runtime_config()
        self.notifier = notifier or TelegramNotifier(logger)
        self.sleep_time = 400

        self.motors: list[Motor] = get_motors() if motors is None else motors
        self._provider_semaphores: dict[str, asyncio.Semaphore] = {}
        self._provider_limits: dict[str, int] = {}
        self._provider_active: Counter[str] = Counter()
        self._provider_waiting: Counter[str] = Counter()
        self._provider_job_counts: Counter[str] = Counter(
            motor.provider_key for motor in self.motors
        )
        self._motors_by_provider: dict[str, list[Motor]] = {}
        self._provider_cycle_health: dict[str, dict[str, Any]] = {}
        for motor in self.motors:
            self._motors_by_provider.setdefault(motor.provider_key, []).append(motor)
            self._configured_provider_limit(motor.provider_key, motor.CONCURRENCY_LIMIT)
            self._ensure_provider_cycle_health(motor.provider_key)
        self.health: dict[str, Any] = initial_health(len(self.motors))
        self._refresh_provider_health()
        if not self.motors:
            logger.critical(
                "No motors were loaded. Check config/jobs.yaml and provider factories. "
                "The scraper will idle until restarted with a valid config."
            )
        else:
            logger.info("Scrapper ready with %d motor(s).", len(self.motors))
            for provider, stats in self.health["providers"].items():
                logger.info(
                    "Provider '%s' ready with %d job(s), concurrency=%d.",
                    provider,
                    stats["job_count"],
                    stats["configured_limit"],
                )

    async def run(self) -> None:
        if not self.motors:
            self.health["status"] = "idle_no_motors"
            logger.warning("Scraper run() has no motors — idling. Restart with a valid config.")
            while True:
                await asyncio.sleep(3600)

        logger.info("Scraper service started.")
        self.health["status"] = "running"
        provider_tasks = [
            asyncio.create_task(
                self._run_provider_loop(provider, motors),
                name=f"scraper-provider-{provider}",
            )
            for provider, motors in self._motors_by_provider.items()
        ]
        await asyncio.gather(*provider_tasks)

    async def _run_provider_loop(self, provider: str, motors: list[Motor]) -> None:
        backoff = self.runtime_config.backoff_initial

        while True:
            start_time = time()
            started_at = self._utc_timestamp()
            provider_health = self._ensure_provider_cycle_health(provider)
            provider_health.update(
                {
                    "status": "running",
                    "last_cycle_started_at": started_at,
                    "last_error": None,
                }
            )
            self._refresh_provider_health()

            try:
                await asyncio.gather(*(self._scrape_with_limit(motor) for motor in motors))
            except Exception as exc:
                provider_health = self._ensure_provider_cycle_health(provider)
                provider_health.update(
                    {
                        "status": "error",
                        "last_error": str(exc),
                    }
                )
                self._refresh_provider_health()
                logger.error("Error during provider '%s' scraping cycle: %s", provider, exc)
                logger.info(
                    "Provider '%s' backing off for %.2fs before retrying.",
                    provider,
                    backoff,
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, self.runtime_config.backoff_max)
                continue

            duration = time() - start_time
            finished_at = self._utc_timestamp()
            backoff = self.runtime_config.backoff_initial
            provider_health = self._ensure_provider_cycle_health(provider)
            provider_health.update(
                {
                    "status": "ok",
                    "last_cycle_finished_at": finished_at,
                    "last_cycle_duration_s": round(duration, 2),
                    "cycle_count": provider_health["cycle_count"] + 1,
                    "last_error": None,
                }
            )
            self.health.update(
                {
                    "status": "ok",
                    "last_cycle_finished_at": finished_at,
                    "last_cycle_duration_s": round(duration, 2),
                }
            )
            self._refresh_provider_health()
            logger.info("Provider '%s' scraping cycle finished in %.2fs.", provider, duration)

            await asyncio.sleep(self.sleep_time)

    async def _scrape_with_limit(self, motor: Motor) -> None:
        await scrape_with_limit(
            motor=motor,
            get_semaphore=self._get_provider_semaphore,
            provider_active=self._provider_active,
            provider_waiting=self._provider_waiting,
            refresh_provider_health=self._refresh_provider_health,
            broadcast=self._broadcast,
            logger=logger,
        )

    def _get_provider_semaphore(self, provider: str, limit: int | None) -> asyncio.Semaphore:
        return get_provider_semaphore(
            provider_semaphores=self._provider_semaphores,
            provider_limits=self._provider_limits,
            provider=provider,
            limit=limit,
            default_provider_concurrency=DEFAULT_PROVIDER_CONCURRENCY,
            logger=logger,
            refresh_provider_health=self._refresh_provider_health,
        )

    def _configured_provider_limit(self, provider: str, limit: int | None) -> int:
        return configured_provider_limit(
            provider_limits=self._provider_limits,
            provider=provider,
            limit=limit,
            default_provider_concurrency=DEFAULT_PROVIDER_CONCURRENCY,
            logger=logger,
        )

    def _ensure_provider_cycle_health(self, provider: str) -> dict[str, Any]:
        return ensure_provider_cycle_health(self._provider_cycle_health, provider)

    def _refresh_provider_health(self) -> None:
        refresh_provider_health(
            health=self.health,
            motors=self.motors,
            provider_limits=self._provider_limits,
            provider_active=self._provider_active,
            provider_waiting=self._provider_waiting,
            provider_job_counts=self._provider_job_counts,
            provider_cycle_health=self._provider_cycle_health,
            default_provider_concurrency=DEFAULT_PROVIDER_CONCURRENCY,
        )

    async def _broadcast(self, broadcast_type: str, element: dict) -> None:
        await self.notifier.broadcast(broadcast_type, element)

    @staticmethod
    def _utc_timestamp() -> str:
        return strftime("%Y-%m-%dT%H:%M:%SZ", gmtime())
