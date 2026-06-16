"""
utils/telegram.py

Telegram notification helpers.

Changes from previous version
──────────────────────────────
• Credentials are now loaded from config/telegram.yaml (gitignored).
  The old utils/secret.py import is gone.

• Guards against missing / blank credentials: if api_token or chat_id
  are absent the module logs a one-time warning at import time and all
  send_* functions become no-ops.  The app never tries to reach Telegram
  without valid config.

• Both public send_* functions are now async and delegate the blocking
  requests.post call to run_in_executor so they never stall the event loop.

• _load_config() raises clear, descriptive errors for the two most common
  mistakes: file not found and missing keys.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Optional

import requests
import yaml

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[1]
_CONFIG_PATH = _REPO_ROOT / "config" / "telegram.yaml"
_PROVIDER_NAMES = {
    "az": "Amazon",
    "lv": "Liverpool",
    "ml": "Mercado Libre",
    "ph": "Palacio de Hierro",
}


def _load_config() -> tuple[str, str]:
    """
    Read api_token and chat_id from config/telegram.yaml.

    Returns ("", "") with a warning when the file is absent or the keys
    are blank — callers treat empty strings as "notifications disabled".
    Never raises; config problems must not crash the application.
    """
    if not _CONFIG_PATH.exists():
        logger.warning(
            "Telegram config not found at '%s'. "
            "Copy config/telegram.yaml.example to config/telegram.yaml "
            "and fill in your credentials to enable notifications.",
            _CONFIG_PATH,
        )
        return "", ""

    try:
        raw = yaml.safe_load(_CONFIG_PATH.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        logger.error("Failed to parse '%s': %s — notifications disabled.", _CONFIG_PATH, exc)
        return "", ""

    token = str(raw.get("api_token", "")).strip()
    chat = str(raw.get("chat_id", "")).strip()

    if not token or not chat:
        logger.warning(
            "'%s' is missing api_token or chat_id. " "Telegram notifications are disabled.",
            _CONFIG_PATH,
        )
        return "", ""

    return token, chat


_API_TOKEN, _CHAT_ID = _load_config()
_ENABLED = bool(_API_TOKEN and _CHAT_ID)
_API_URL = f"https://api.telegram.org/bot{_API_TOKEN}/sendMessage" if _ENABLED else ""


async def send_new_to_telegram(element: dict) -> None:
    """Send a new-listing notification.  No-op when credentials are missing."""
    if not _ENABLED:
        return
    message = _format_new_item(element)
    await _send_async(message)


async def send_price_drop_to_telegram(element: dict) -> None:
    """Send a price-drop notification.  No-op when credentials are missing."""
    if not _ENABLED:
        return
    message = _format_price_drop(element)
    if message:
        await _send_async(message)


async def _send_async(message: str) -> None:
    """
    Dispatch message in a thread-pool executor so the async event loop
    is never blocked by the synchronous requests.post call.
    """
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _send_sync, message)


def _send_sync(message: str) -> None:
    """Blocking send — always called from a thread, never from the event loop."""
    try:
        response = requests.post(
            _API_URL,
            json={
                "chat_id": _CHAT_ID,
                "parse_mode": "html",
                "text": message,
                "disable_web_page_preview": False,
            },
            timeout=10,
        )
        response.raise_for_status()
    except Exception as exc:
        logger.error("Telegram send failed: %s", exc)


def _format_new_item(element: dict) -> str:
    job_id = escape(str(element.get("job_id", "New item")))
    title = escape(str(element.get("title", "Untitled")))
    price = _coerce_number(element.get("price", 0))
    provider = _format_provider(element.get("provider"))
    first_seen = _format_timestamp(element.get("datetime"))
    link = _format_product_link(element.get("url"))

    return (
        f"🆕 <b>${price:,.2f} MXN</b>  {title}\n\n"
        f"<i>Product</i>\n"
        f"<b>{title}</b>\n\n"
        f"<i>Listing details</i>\n"
        f"💰 Price: <b>${price:,.2f} MXN</b>\n"
        f"🏪 Provider: <b>{provider}</b>\n"
        f"🔎 Monitor: {job_id}\n\n"
        f"🕒 Found: {first_seen}\n\n"
        f"{link}"
    )


def _format_price_drop(element: dict) -> Optional[str]:
    if not element.get("percent_change"):
        return None

    job_id = escape(str(element.get("job_id", "Item")))
    title = escape(str(element.get("title", "Untitled")))
    history = element.get("history", [{}])
    last_price = _coerce_number(
        element.get("previous_price", history[0].get("price", 0) if history else 0)
    )
    price = _coerce_number(element.get("new_price", element.get("price", 0)))
    percent_change = abs(_coerce_number(element.get("percent_change", 0)))
    provider = _format_provider(element.get("provider"))
    first_seen = _format_timestamp(element.get("datetime"))
    updated = element.get("last_updated")
    savings = last_price - price
    link = _format_product_link(element.get("url"))
    time_lines = f"🕒 Found: {first_seen}"
    if updated:
        time_lines += f"\n🕒 Updated: {_format_timestamp(updated)}"

    return (
        f"🔥 <b>{percent_change:.1f}% OFF</b>  <s>${last_price:,.2f}</s> -> "
        f"<b>${price:,.2f} MXN</b>  {title}\n\n"
        f"<i>Product</i>\n"
        f"<b>{title}</b>\n\n"
        f"<i>Price details</i>\n"
        f"Previous price: <s>${last_price:,.2f} MXN</s>\n"
        f"Current price: <b>${price:,.2f} MXN</b>\n"
        f"Savings: <b>${savings:,.2f} MXN</b>\n"
        f"Reduction from previous: <b>{percent_change:.1f}%</b>\n\n"
        f"<i>Source</i>\n"
        f"🏪 Provider: <b>{provider}</b>\n"
        f"🔎 Monitor: {job_id}\n\n"
        f"{time_lines}\n\n"
        f"{link}"
    )


def _format_provider(provider: object) -> str:
    value = str(provider or "Unknown")
    return escape(_PROVIDER_NAMES.get(value, value))


def _format_timestamp(value: object) -> str:
    text = str(value or "Unknown")
    if len(text) <= 10:
        return escape(text)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return escape(text)
    return escape(parsed.strftime("%Y-%m-%d %H:%M"))


def _format_product_link(url: object) -> str:
    value = str(url or "").strip()
    if not value:
        return "🔗 Product link unavailable"
    return f'🔗 <a href="{escape(value, quote=True)}">Open product</a>'


def _coerce_number(value: object) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.replace(",", "").strip()
        if cleaned:
            try:
                return float(cleaned)
            except ValueError:
                return 0.0
    return 0.0
