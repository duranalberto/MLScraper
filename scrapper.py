"""
Orchestrator — runs all motors on a schedule and routes notification events.
"""

import asyncio
import logging
from collections import Counter
from functools import lru_cache
from pathlib import Path
from time import gmtime, strftime, time
from typing import Optional, Any

import yaml

from provider.generator import get_motors
from scraper.motor import Motor
from utils.telegram import send_new_to_telegram, send_price_drop_to_telegram

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)
_CONFIG_PATH = Path(__file__).resolve().parent / "config" / "scrapper.yaml"


@lru_cache(maxsize=1)
def _load_scrapper_config() -> dict[str, Any]:
    if not _CONFIG_PATH.exists():
        raise FileNotFoundError(
            f"Scrapper config file not found: '{_CONFIG_PATH.resolve()}'. "
            "Create config/scrapper.yaml to define orchestration policy values."
        )

    with _CONFIG_PATH.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}

    if not isinstance(data, dict):
        raise ValueError(
            f"'{_CONFIG_PATH}' must contain a YAML mapping at the top level."
        )

    required = ("BACKOFF_INITIAL", "BACKOFF_MAX")
    missing = [key for key in required if key not in data]
    if missing:
        raise KeyError(
            f"Missing required scrapper config key(s) {missing!r} in '{_CONFIG_PATH}'."
        )

    return data


_SCRAPPER_CONFIG = _load_scrapper_config()
DEFAULT_PROVIDER_CONCURRENCY = int(
    _SCRAPPER_CONFIG.get(
        "DEFAULT_PROVIDER_CONCURRENCY",
        _SCRAPPER_CONFIG.get("MAX_CONCURRENT_MOTORS", 1),
    )
)
_BACKOFF_INITIAL = int(_SCRAPPER_CONFIG["BACKOFF_INITIAL"])
_BACKOFF_MAX = int(_SCRAPPER_CONFIG["BACKOFF_MAX"])


class Scrapper:
    def __init__(self):
        self.sleep_time = 400

        self.motors: list[Motor] = get_motors()
        self._provider_semaphores: dict[str, asyncio.Semaphore] = {}
        self._provider_limits: dict[str, int] = {}
        self._provider_active: Counter[str] = Counter()
        self._provider_waiting: Counter[str] = Counter()
        self._provider_job_counts: Counter[str] = Counter(motor.provider_key for motor in self.motors)
        self._motors_by_provider: dict[str, list[Motor]] = {}
        self._provider_cycle_health: dict[str, dict[str, Any]] = {}
        for motor in self.motors:
            self._motors_by_provider.setdefault(motor.provider_key, []).append(motor)
            self._configured_provider_limit(motor.provider_key, motor.CONCURRENCY_LIMIT)
            self._ensure_provider_cycle_health(motor.provider_key)
        self.health: dict[str, Any] = {
            "status": "starting",
            "last_cycle_finished_at": None,
            "last_cycle_duration_s": None,
            "motor_count": len(self.motors),
            "providers": {},
        }
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
        backoff = _BACKOFF_INITIAL

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
                await asyncio.gather(
                    *(self._scrape_with_limit(motor) for motor in motors)
                )
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
                backoff = min(backoff * 2, _BACKOFF_MAX)
                continue

            duration = time() - start_time
            finished_at = self._utc_timestamp()
            backoff = _BACKOFF_INITIAL
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
        provider = motor.provider_key
        semaphore = self._get_provider_semaphore(provider, motor.CONCURRENCY_LIMIT)
        acquired = False
        self._provider_waiting[provider] += 1
        self._refresh_provider_health()
        try:
            async with semaphore:
                acquired = True
                self._provider_waiting[provider] -= 1
                self._provider_active[provider] += 1
                self._refresh_provider_health()
                try:
                    await motor.scrape(caller=self._broadcast, silent=True)
                finally:
                    self._provider_active[provider] -= 1
                    self._refresh_provider_health()
        except Exception:
            logger.exception(
                "Motor '%s' (%s) failed during scrape; continuing with the remaining motors.",
                motor.search_term,
                provider,
            )
        finally:
            if not acquired:
                self._provider_waiting[provider] -= 1
            self._refresh_provider_health()

    def _get_provider_semaphore(self, provider: str, limit: int | None) -> asyncio.Semaphore:
        limit = self._configured_provider_limit(provider, limit)

        semaphore = self._provider_semaphores.get(provider)
        if semaphore is None:
            self._provider_semaphores[provider] = asyncio.Semaphore(limit)
            self._provider_limits[provider] = limit
            self._refresh_provider_health()
        elif self._provider_limits.get(provider) != limit:
            logger.warning(
                "Provider '%s' requested concurrency %d but already has %d; keeping the first configured value.",
                provider,
                limit,
                self._provider_limits.get(provider, limit),
            )
        return self._provider_semaphores[provider]

    def _configured_provider_limit(self, provider: str, limit: int | None) -> int:
        existing = self._provider_limits.get(provider)
        if limit is None:
            limit = DEFAULT_PROVIDER_CONCURRENCY
        elif limit < 1:
            if existing is None:
                logger.warning(
                    "Provider '%s' requested invalid concurrency %d; clamping to 1.",
                    provider,
                    limit,
                )
            limit = 1

        if existing is None:
            self._provider_limits[provider] = limit
        elif existing != limit:
            logger.warning(
                "Provider '%s' requested concurrency %d but already has %d; keeping the first configured value.",
                provider,
                limit,
                existing,
            )
            limit = existing
        return limit

    def _ensure_provider_cycle_health(self, provider: str) -> dict[str, Any]:
        return self._provider_cycle_health.setdefault(
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

    def _refresh_provider_health(self) -> None:
        providers = set(self._provider_job_counts)
        providers.update(self._provider_limits)
        providers.update(self._provider_active)
        providers.update(self._provider_waiting)
        providers.update(self._provider_cycle_health)
        self.health["providers"] = {
            provider: {
                **self._ensure_provider_cycle_health(provider),
                "configured_limit": self._provider_limits.get(provider, DEFAULT_PROVIDER_CONCURRENCY),
                "job_count": self._provider_job_counts.get(provider, 0),
                "active_jobs": max(0, self._provider_active.get(provider, 0)),
                "queued_jobs": max(0, self._provider_waiting.get(provider, 0)),
                "blocked_jobs": sum(
                    1
                    for motor in self.motors
                    if motor.provider_key == provider and motor.blocked_reason
                ),
                "block_reasons": sorted(
                    {
                        motor.blocked_reason
                        for motor in self.motors
                        if motor.provider_key == provider and motor.blocked_reason
                    }
                    - {None}
                ),
            }
            for provider in sorted(providers)
        }

    async def _broadcast(self, broadcast_type: str, element: dict) -> None:
        if broadcast_type == "new_element":
            await self._broadcast_new_element(element)
        elif broadcast_type == "is_updated":
            await self._broadcast_is_updated(element)
        else:
            logger.warning("Unknown broadcast_type '%s' — ignored.", broadcast_type)

    async def _broadcast_new_element(self, element: dict) -> None:
        await send_new_to_telegram(element)

    async def _broadcast_is_updated(self, element: dict) -> None:
        history = element.get("history", [])
        if not history or "price" not in history[0]:
            return

        last_value = self._parse_price(history[0]["price"])
        new_value  = self._parse_price(element.get("price"))

        if last_value is None or new_value is None:
            logger.debug("Skipping price-drop check for '%s': unparseable price value.", element.get("title", "<unknown>"))
            return

        if last_value <= 0:
            return

        percent_change = ((new_value - last_value) / abs(last_value)) * 100

        if percent_change <= -14:
            element["percent_change"] = f"{abs(percent_change):.2f}"
            logger.info("PRICE DROP: %s (%s%%) — %s", element.get("title"), element["percent_change"], element.get("url"))
            await send_price_drop_to_telegram(element)

    @staticmethod
    def _parse_price(value: Any) -> Optional[float]:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            cleaned = value.replace(",", "").strip()
            if not cleaned:
                return None
            try:
                return float(cleaned)
            except ValueError:
                return None
        return None

    @staticmethod
    def _utc_timestamp() -> str:
        return strftime("%Y-%m-%dT%H:%M:%SZ", gmtime())


if __name__ == "__main__":
    scraper = Scrapper()
    try:
        asyncio.run(scraper.run())
    except KeyboardInterrupt:
        logger.info("Scraper stopped by user.")
