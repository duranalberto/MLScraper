"""
utils/file_manager.py

File persistence helpers.
Supports sub-directory paths under the shared DATA_PATH root.
All callers pass a relative path such as "mercado_libre/zelda-wii.json";
this module ensures the parent directory exists before every write.
"""

import asyncio
import json
import logging
import os
import shutil
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DATA_PATH = Path(os.environ.get("DATA_PATH", "./data")).expanduser().resolve()
_TMP_SUFFIX = ".tmp"
_BACKUP_SUFFIX = ".bak"
JsonList = list[Any]


def _safe_relative_path(relative_path: str) -> Path:
    """Return a normalized relative path and reject path traversal."""
    path = Path(relative_path)
    if path.is_absolute():
        raise ValueError(f"Absolute paths are not allowed: {relative_path!r}")
    if any(part == ".." for part in path.parts):
        raise ValueError(f"Parent-directory traversal is not allowed: {relative_path!r}")
    return path


def _resolve(relative_path: str) -> Path:
    """Return the absolute Path for *relative_path* under DATA_PATH."""
    path = Path(relative_path).expanduser()
    if path.is_absolute():
        resolved = path.resolve()
        root = DATA_PATH
        if resolved == root or root in resolved.parents:
            return resolved
        raise ValueError(f"Absolute paths must stay under DATA_PATH: {relative_path!r}")
    return DATA_PATH / _safe_relative_path(relative_path)


def _backup_path(path: Path) -> Path:
    return path.with_name(f"{path.name}{_BACKUP_SUFFIX}")


def _load_json_list(path: Path) -> JsonList | None:
    if not path.exists():
        return None

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        logger.error("Invalid JSON in '%s'.", path)
        return None
    except Exception as exc:
        logger.error("Unexpected error reading '%s': %s", path, exc)
        return None

    if not isinstance(data, list):
        logger.error(
            "Invalid JSON root in '%s' — expected a list, got %s.",
            path,
            type(data).__name__,
        )
        return None

    return data


def _ensure_parent(path: Path) -> None:
    """Create parent directories if they don't exist."""
    path.parent.mkdir(parents=True, exist_ok=True)


def write_in_file_sync(relative_path: str, content: str) -> None:
    """Synchronous write; creates directories and file as needed."""
    if not relative_path or content is None:
        return
    path = _resolve(relative_path)
    _ensure_parent(path)
    tmp_path = path.with_name(f"{path.name}{_TMP_SUFFIX}")
    backup_path = _backup_path(path)

    if path.exists():
        try:
            shutil.copy2(path, backup_path)
        except Exception as exc:
            logger.warning("Failed to create backup '%s': %s", backup_path, exc)

    tmp_path.write_text(content, encoding="utf-8")
    os.replace(tmp_path, path)


async def write_in_file(relative_path: str, content: str) -> None:
    """
    Async write that delegates blocking I/O to a thread-pool executor
    so it never blocks the event loop.
    """
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, write_in_file_sync, relative_path, content)


def read_json_file(relative_path: str) -> JsonList:
    """Read a JSON list from *relative_path*; returns [] on missing file or parse error."""
    path = _resolve(relative_path)
    data = _load_json_list(path)
    if data is not None:
        return data

    backup = _backup_path(path)
    recovered = _load_json_list(backup)
    if recovered is not None:
        logger.warning("Recovered '%s' from backup '%s'.", path, backup)
        return recovered

    return []
