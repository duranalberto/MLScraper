"""
Orchestrator — runs all motors on a schedule and routes broadcast events.
"""

import asyncio
import logging
from json import dumps as json_dumps
from functools import lru_cache
from pathlib import Path
from time import gmtime, strftime, time
from typing import Optional, Callable, Any

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

    required = ("MAX_CONCURRENT_MOTORS", "BACKOFF_INITIAL", "BACKOFF_MAX")
    missing = [key for key in required if key not in data]
    if missing:
        raise KeyError(
            f"Missing required scrapper config key(s) {missing!r} in '{_CONFIG_PATH}'."
        )

    return data


_SCRAPPER_CONFIG = _load_scrapper_config()
MAX_CONCURRENT_MOTORS = int(_SCRAPPER_CONFIG["MAX_CONCURRENT_MOTORS"])
_BACKOFF_INITIAL = int(_SCRAPPER_CONFIG["BACKOFF_INITIAL"])
_BACKOFF_MAX = int(_SCRAPPER_CONFIG["BACKOFF_MAX"])


class Scrapper:
    def __init__(self, caller: Optional[Callable] = None):
        self.sleep_time = 400
        self.caller     = caller

        self.motors: list[Motor] = get_motors()
        self._domain_semaphores: dict[str, asyncio.Semaphore] = {}
        self._domain_limits: dict[str, int] = {}
        self.health: dict[str, Any] = {
            "status": "starting",
            "last_cycle_finished_at": None,
            "last_cycle_duration_s": None,
            "motor_count": len(self.motors),
        }
        if not self.motors:
            logger.critical(
                "No motors were loaded. Check config/jobs.yaml and provider factories. "
                "The scraper will idle until restarted with a valid config."
            )
        else:
            logger.info("Scrapper ready with %d motor(s).", len(self.motors))


    def get_list(self) -> list[dict]:
        return [
            {
                "title":    motor.search_term,
                "elements": [motor._article_payload(a) for a in motor.active],
            }
            for motor in self.motors
        ]

    async def run(self) -> None:
        if not self.motors:
            self.health["status"] = "idle_no_motors"
            logger.warning("Scraper run() has no motors — idling. Restart with a valid config.")
            while True:
                await asyncio.sleep(3600)

        logger.info("Scraper service started.")
        self.health["status"] = "running"
        backoff = _BACKOFF_INITIAL

        while True:
            start_time = time()
            try:
                await asyncio.gather(
                    *[self._scrape_with_limit(motor) for motor in self.motors]
                )
                duration   = time() - start_time
                backoff    = _BACKOFF_INITIAL
                status_msg = f"Scraping cycle finished in {duration:.2f}s."
                self.health.update(
                    {
                        "status": "ok",
                        "last_cycle_finished_at": strftime("%Y-%m-%dT%H:%M:%SZ", gmtime()),
                        "last_cycle_duration_s": round(duration, 2),
                    }
                )
                logger.info(status_msg)
                await self._broadcast_scrape_finished(status_msg)

            except Exception as exc:
                self.health["status"] = "error"
                logger.error("Error during scraping cycle: %s", exc)
                logger.info("Backing off for %ds before retrying.", backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, _BACKOFF_MAX)
                continue

            await asyncio.sleep(self.sleep_time)


    async def _scrape_with_limit(self, motor: Motor) -> None:
        async with self._get_domain_semaphore(motor.domain, motor.CONCURRENCY_LIMIT):
            await motor.scrape(caller=self._broadcast, silent=True)

    def _get_domain_semaphore(self, domain: str, limit: int | None) -> asyncio.Semaphore:
        if limit is None:
            limit = MAX_CONCURRENT_MOTORS

        semaphore = self._domain_semaphores.get(domain)
        if semaphore is None:
            self._domain_semaphores[domain] = asyncio.Semaphore(limit)
            self._domain_limits[domain] = limit
        elif self._domain_limits.get(domain) != limit:
            logger.warning(
                "Domain '%s' requested concurrency %d but already has %d; keeping the first configured value.",
                domain,
                limit,
                self._domain_limits.get(domain, limit),
            )
        return self._domain_semaphores[domain]

    async def _broadcast(self, broadcast_type: str, element: dict) -> None:
        if broadcast_type == "new_element":
            await self._broadcast_new_element(element)
        elif broadcast_type == "is_updated":
            await self._broadcast_is_updated(element)
        else:
            logger.warning("Unknown broadcast_type '%s' — ignored.", broadcast_type)

    async def _broadcast_new_element(self, element: dict) -> None:
        response = {"message": "new element", "payload": element}
        await send_new_to_telegram(element)
        if self.caller:
            try:
                await self.caller(json_dumps(response))
            except Exception as exc:
                logger.error("WebSocket broadcast failed (new_element): %s", exc)

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
            if self.caller:
                try:
                    await self.caller(json_dumps({"message": "price drop", "payload": element}))
                except Exception as exc:
                    logger.error("WebSocket broadcast failed (price_drop): %s", exc)

    async def _broadcast_scrape_finished(self, status_text: str) -> None:
        if self.caller:
            try:
                await self.caller(json_dumps({"message": "scrape status", "payload": status_text}))
            except Exception as exc:
                logger.error("WebSocket broadcast failed (scrape_status): %s", exc)

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


if __name__ == "__main__":
    scraper = Scrapper()
    try:
        asyncio.run(scraper.run())
    except KeyboardInterrupt:
        logger.info("Scraper stopped by user.")
