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
from pathlib import Path
from typing import Optional

import requests
import yaml

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path("config/telegram.yaml")

# ---------------------------------------------------------------------------
# Credential loading
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Public async API
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


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
    search_term = element.get("search_term", "New item")
    title = element.get("title", "Untitled")
    url = element.get("url", "")
    price = element.get("price", 0)
    dt = element.get("datetime", "Unknown")

    return (
        f"🆕 <b>NEW LISTING</b>\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"📦 <b>{search_term}</b>\n\n"
        f'<a href="{url}">{title}</a>\n\n'
        f"💰 <b>${price:,.2f} MXN</b>\n"
        f"🕒 {dt}"
    )


def _format_price_drop(element: dict) -> Optional[str]:
    if not element.get("percent_change"):
        return None

    search_term = element.get("search_term", "Item")
    title = element.get("title", "Untitled")
    url = element.get("url", "")
    price = element.get("price", 0)
    percent_change = abs(element.get("percent_change", 0))
    history = element.get("history", [{}])
    last_price = history[0].get("price", 0) if history else 0
    dt = history[0].get("datetime", "Unknown") if history else "Unknown"
    savings = last_price - price

    return (
        f"🔥 <b>PRICE DROP ALERT!</b>\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"📦 <b>{search_term}</b>\n\n"
        f'<a href="{url}">{title}</a>\n\n'
        f"<s>${last_price:,.2f}</s> ➜ <b>${price:,.2f} MXN</b>\n"
        f"💸 Save ${savings:,.2f} ({percent_change:.1f}% OFF)\n\n"
        f"🕒 Updated: {dt}"
    )
