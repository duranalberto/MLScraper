from __future__ import annotations

import logging
from typing import Any, Optional

from scraper.runtime.notifications import (
    broadcast as route_broadcast,
    broadcast_is_updated,
    broadcast_new_element,
    parse_price,
)
from utils.telegram import send_new_to_telegram, send_price_drop_to_telegram


class TelegramNotifier:
    def __init__(self, logger: logging.Logger) -> None:
        self.logger = logger

    async def broadcast(self, broadcast_type: str, element: dict) -> None:
        await route_broadcast(
            broadcast_type=broadcast_type,
            element=element,
            send_new=send_new_to_telegram,
            send_price_drop=send_price_drop_to_telegram,
            logger=self.logger,
        )

    async def broadcast_new_element(self, element: dict) -> None:
        await broadcast_new_element(
            element,
            send_new=send_new_to_telegram,
            logger=self.logger,
        )

    async def broadcast_is_updated(self, element: dict) -> None:
        await broadcast_is_updated(
            element,
            send_price_drop=send_price_drop_to_telegram,
            logger=self.logger,
        )

    @staticmethod
    def parse_price(value: Any) -> Optional[float]:
        return parse_price(value)
