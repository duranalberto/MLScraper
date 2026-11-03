"""Telegram observer and default notification dispatcher wiring."""

from __future__ import annotations

import logging
from typing import Any, Optional, Sequence

from scraper.runtime.notifications import (
    NotificationDispatcher,
    NotificationEvent,
    NotificationEventType,
    NotificationObserver,
    broadcast_is_updated,
    broadcast_new_element,
    parse_price,
)
from utils.telegram import send_new_to_telegram, send_price_drop_to_telegram


class TelegramObserver:
    """Notification observer that delivers new-item and price-drop alerts to Telegram."""

    async def notify(self, event: NotificationEvent) -> None:
        """Send ``event`` to Telegram according to its ``event_type``."""
        if event.event_type is NotificationEventType.NEW_ELEMENT:
            await send_new_to_telegram(event.element)
        elif event.event_type is NotificationEventType.PRICE_DROP:
            await send_price_drop_to_telegram(event.element)


class TelegramNotifier(NotificationDispatcher):
    """Queue-backed notification dispatcher pre-configured with :class:`TelegramObserver`.

    Inherits full async queue decoupling and multi-observer registration from
    :class:`NotificationDispatcher` while remaining a drop-in replacement for
    legacy ``TelegramNotifier`` callers.
    """

    def __init__(
        self,
        logger: logging.Logger,
        *,
        observers: Sequence[NotificationObserver] | None = None,
        max_queue_size: int = 0,
    ) -> None:
        resolved_observers = list(observers) if observers is not None else [TelegramObserver()]
        super().__init__(
            logger,
            observers=resolved_observers,
            max_queue_size=max_queue_size,
        )

    async def broadcast_new_element(self, element: dict) -> None:
        """Evaluate and send a new-element notification directly."""
        await broadcast_new_element(
            element,
            send_new=send_new_to_telegram,
            logger=self.logger,
        )

    async def broadcast_is_updated(self, element: dict) -> None:
        """Evaluate and send a price-drop notification directly."""
        await broadcast_is_updated(
            element,
            send_price_drop=send_price_drop_to_telegram,
            logger=self.logger,
        )

    @staticmethod
    def parse_price(value: Any) -> Optional[float]:
        """Parse a numeric or comma-formatted string price into a float."""
        return parse_price(value)
