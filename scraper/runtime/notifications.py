"""Notification event evaluation, observer contracts, and async queue dispatcher.

This module decouples scraping motors from external notification channels using
two complementary patterns:

1. **Producer-Consumer Queue (`NotificationDispatcher`)**: Scraping motors
   enqueue raw article discovery/update events onto an ``asyncio.Queue`` in
   $O(1)$ time without waiting for network I/O. A background consumer task
   drains the queue asynchronously.
2. **Observer Pattern (`NotificationObserver`)**: Once a raw event satisfies
   domain notification rules (non-initial new listing or $\\ge 14\\%$ price
   drop), ``NotificationDispatcher`` fans out an immutable
   ``NotificationEvent`` concurrently to all registered observers (e.g.,
   Telegram, and future Slack/Discord/Webhook observers).
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass
from enum import Enum
import logging
from typing import Any, Awaitable, Callable, Optional, Protocol, Sequence, runtime_checkable

PRICE_DROP_THRESHOLD_PERCENT = -14.0


class NotificationEventType(str, Enum):
    """Supported domain notification event types."""

    NEW_ELEMENT = "new_element"
    PRICE_DROP = "price_drop"


@dataclass(frozen=True)
class NotificationEvent:
    """Evaluated domain notification event dispatched to observers.

    Args:
        event_type: Whether the event represents a new listing or a price drop.
        element: Enriched article dictionary containing motor context and, for
            price drops, ``previous_price``, ``new_price``, and ``percent_change``.
    """

    event_type: NotificationEventType
    element: dict[str, Any]


@runtime_checkable
class NotificationObserver(Protocol):
    """Observer contract for receiving evaluated scraper notification events."""

    async def notify(self, event: NotificationEvent) -> None:
        """Handle a single evaluated notification event."""


class CallableNotificationObserver:
    """Observer adapter that routes events to ``send_new`` and ``send_price_drop`` callables."""

    def __init__(
        self,
        *,
        send_new: Callable[[dict[str, Any]], Awaitable[None]],
        send_price_drop: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None:
        self._send_new = send_new
        self._send_price_drop = send_price_drop

    async def notify(self, event: NotificationEvent) -> None:
        """Dispatch ``event`` to the matching async callback."""
        if event.event_type is NotificationEventType.NEW_ELEMENT:
            await self._send_new(event.element)
        elif event.event_type is NotificationEventType.PRICE_DROP:
            await self._send_price_drop(event.element)


def evaluate_notification_event(
    *,
    broadcast_type: str,
    element: dict[str, Any],
    logger: logging.Logger,
) -> NotificationEvent | None:
    """Evaluate domain rules for a raw scrape broadcast and return an event if actionable.

    Args:
        broadcast_type: Raw broadcast identifier (``"new_element"`` or ``"is_updated"``).
        element: Serialized article payload enriched with motor context.
        logger: Logger used for domain event and diagnostic logging.

    Returns:
        A ``NotificationEvent`` when the event should be sent to observers, or
        ``None`` when filtered out by domain rules.
    """
    if broadcast_type == "new_element":
        if element.get("is_initial_scrape", False):
            return None

        logger.info(
            "NEW ITEM: %s | %s | $%s | %s",
            element.get("job_id", "New item"),
            element.get("title", "Untitled"),
            element.get("price", "unknown"),
            element.get("url", ""),
        )
        return NotificationEvent(
            event_type=NotificationEventType.NEW_ELEMENT,
            element=dict(element),
        )

    if broadcast_type == "is_updated":
        history = element.get("history", [])
        if not history or "price" not in history[0]:
            return None

        last_value = parse_price(history[0]["price"])
        new_value = parse_price(element.get("price"))

        if last_value is None or new_value is None:
            logger.debug(
                "Skipping price-drop check for '%s': unparseable price value.",
                element.get("title", "<unknown>"),
            )
            return None

        if last_value <= 0:
            return None

        percent_change = ((new_value - last_value) / abs(last_value)) * 100

        if percent_change <= PRICE_DROP_THRESHOLD_PERCENT:
            element["percent_change"] = f"{abs(percent_change):.2f}"
            element["previous_price"] = last_value
            element["new_price"] = new_value
            logger.info(
                "PRICE DROP: %s | $%.2f -> $%.2f (%s%%) — %s",
                element.get("title"),
                last_value,
                new_value,
                element["percent_change"],
                element.get("url"),
            )
            return NotificationEvent(
                event_type=NotificationEventType.PRICE_DROP,
                element=dict(element),
            )
        return None

    logger.warning("Unknown broadcast_type '%s' — ignored.", broadcast_type)
    return None


class NotificationDispatcher:
    """Queue-backed notification subject that dispatches events to observers.

    When the background consumer worker is running (started via :meth:`start`),
    calls to :meth:`broadcast` or :meth:`enqueue` place events onto an internal
    ``asyncio.Queue`` and return immediately so scraping loops are never delayed
    by notification transport I/O. When the worker is not running, :meth:`broadcast`
    evaluates and notifies observers inline for synchronous test convenience.
    """

    def __init__(
        self,
        logger: logging.Logger,
        *,
        observers: Sequence[NotificationObserver] = (),
        max_queue_size: int = 0,
    ) -> None:
        self.logger = logger
        self._observers: list[NotificationObserver] = list(observers)
        self._queue: asyncio.Queue[tuple[str, dict[str, Any]] | None] = asyncio.Queue(
            maxsize=max_queue_size
        )
        self._worker_task: asyncio.Task[None] | None = None

    @property
    def observers(self) -> tuple[NotificationObserver, ...]:
        """Return the registered notification observers."""
        return tuple(self._observers)

    @property
    def pending_count(self) -> int:
        """Return the number of queued events awaiting background dispatch."""
        return self._queue.qsize()

    @property
    def is_running(self) -> bool:
        """Return ``True`` when the background queue consumer task is active."""
        return self._worker_task is not None and not self._worker_task.done()

    def add_observer(self, observer: NotificationObserver) -> None:
        """Register an observer to receive future notification events."""
        if observer not in self._observers:
            self._observers.append(observer)

    def remove_observer(self, observer: NotificationObserver) -> None:
        """Unregister a previously added observer if present."""
        if observer in self._observers:
            self._observers.remove(observer)

    def start(self) -> asyncio.Task[None]:
        """Start the background queue consumer task on the current event loop."""
        if self._worker_task is None or self._worker_task.done():
            self._worker_task = asyncio.create_task(
                self._consume_loop(),
                name="scraper-notification-dispatcher",
            )
        return self._worker_task

    async def stop(self, *, drain: bool = True) -> None:
        """Stop the background queue consumer task.

        Args:
            drain: When ``True``, process all currently queued events before
                stopping the worker task.
        """
        task = self._worker_task
        if task is None:
            return

        if not task.done():
            if drain:
                await self._queue.put(None)
                with suppress(asyncio.CancelledError):
                    await task
            else:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
        self._worker_task = None

    def enqueue(self, broadcast_type: str, element: dict[str, Any]) -> None:
        """Enqueue a raw notification event without blocking the caller."""
        self._queue.put_nowait((broadcast_type, dict(element)))

    async def broadcast(self, broadcast_type: str, element: dict[str, Any]) -> None:
        """Publish a scrape event via the async queue (or inline if worker is stopped)."""
        if self.is_running:
            self.enqueue(broadcast_type, element)
            return

        await self._process_raw_event(broadcast_type, element)

    async def _consume_loop(self) -> None:
        """Background consumer loop that drains the queue and notifies observers."""
        while True:
            item = await self._queue.get()
            try:
                if item is None:
                    return
                broadcast_type, element = item
                await self._process_raw_event(broadcast_type, element)
            except Exception as exc:
                self.logger.error("Unexpected error in notification dispatcher: %s", exc)
            finally:
                self._queue.task_done()

    async def _process_raw_event(self, broadcast_type: str, element: dict[str, Any]) -> None:
        """Evaluate domain rules and fan out actionable events to all observers."""
        event = evaluate_notification_event(
            broadcast_type=broadcast_type,
            element=element,
            logger=self.logger,
        )
        if event is None or not self._observers:
            return

        await self.notify_observers(event)

    async def notify_observers(self, event: NotificationEvent) -> None:
        """Fan out ``event`` concurrently to all registered observers."""
        await asyncio.gather(
            *(self._notify_single(observer, event) for observer in self._observers),
            return_exceptions=True,
        )

    async def _notify_single(
        self,
        observer: NotificationObserver,
        event: NotificationEvent,
    ) -> None:
        try:
            await observer.notify(event)
        except Exception as exc:
            self.logger.error(
                "Notification observer %s failed for %s: %s",
                type(observer).__name__,
                event.event_type.value,
                exc,
            )


async def broadcast(
    *,
    broadcast_type: str,
    element: dict,
    send_new: Callable[[dict], Awaitable[None]],
    send_price_drop: Callable[[dict], Awaitable[None]],
    logger: logging.Logger,
) -> None:
    """Route a raw broadcast event to ``send_new`` or ``send_price_drop`` callbacks."""
    observer = CallableNotificationObserver(
        send_new=send_new,
        send_price_drop=send_price_drop,
    )
    event = evaluate_notification_event(
        broadcast_type=broadcast_type,
        element=element,
        logger=logger,
    )
    if event is not None:
        await observer.notify(event)


async def broadcast_new_element(
    element: dict,
    *,
    send_new: Callable[[dict], Awaitable[None]],
    logger: logging.Logger,
) -> None:
    """Send new-item notifications after the initial scrape baseline exists.

    Args:
        element: Serialized article payload enriched with motor context. When
            ``is_initial_scrape`` is true, the item belongs to a newly created
            job's first successful scrape and is intentionally silenced.
        send_new: Async callback that dispatches the new-item notification.
        logger: Logger used for notification routing diagnostics.
    """
    event = evaluate_notification_event(
        broadcast_type="new_element",
        element=element,
        logger=logger,
    )
    if event is not None:
        await send_new(element)


async def broadcast_is_updated(
    element: dict,
    *,
    send_price_drop: Callable[[dict], Awaitable[None]],
    logger: logging.Logger,
) -> None:
    """Evaluate an updated article for a significant price drop and notify."""
    event = evaluate_notification_event(
        broadcast_type="is_updated",
        element=element,
        logger=logger,
    )
    if event is not None:
        await send_price_drop(element)


def parse_price(value: Any) -> Optional[float]:
    """Parse a numeric or comma-formatted string price into a float."""
    if value is None or isinstance(value, bool):
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
