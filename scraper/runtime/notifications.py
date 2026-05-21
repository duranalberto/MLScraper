from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Optional


async def broadcast(
    *,
    broadcast_type: str,
    element: dict,
    send_new: Callable[[dict], Awaitable[None]],
    send_price_drop: Callable[[dict], Awaitable[None]],
    logger: logging.Logger,
) -> None:
    if broadcast_type == "new_element":
        await broadcast_new_element(element, send_new=send_new, logger=logger)
    elif broadcast_type == "is_updated":
        await broadcast_is_updated(
            element,
            send_price_drop=send_price_drop,
            logger=logger,
        )
    else:
        logger.warning("Unknown broadcast_type '%s' — ignored.", broadcast_type)


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
    if element.get("is_initial_scrape", False):
        return

    logger.info(
        "NEW ITEM: %s | %s | $%s | %s",
        element.get("search_term", "New item"),
        element.get("title", "Untitled"),
        element.get("price", "unknown"),
        element.get("url", ""),
    )
    await send_new(element)


async def broadcast_is_updated(
    element: dict,
    *,
    send_price_drop: Callable[[dict], Awaitable[None]],
    logger: logging.Logger,
) -> None:
    history = element.get("history", [])
    if not history or "price" not in history[0]:
        return

    last_value = parse_price(history[0]["price"])
    new_value = parse_price(element.get("price"))

    if last_value is None or new_value is None:
        logger.debug(
            "Skipping price-drop check for '%s': unparseable price value.",
            element.get("title", "<unknown>"),
        )
        return

    if last_value <= 0:
        return

    percent_change = ((new_value - last_value) / abs(last_value)) * 100

    if percent_change <= -14:
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
        await send_price_drop(element)


def parse_price(value: Any) -> Optional[float]:
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
