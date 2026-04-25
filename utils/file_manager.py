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
from typing import Union, List, Dict

logger = logging.getLogger(__name__)

DATA_PATH = Path(os.environ.get("DATA_PATH", "./data"))
_TMP_SUFFIX = ".tmp"
_BACKUP_SUFFIX = ".bak"


def _resolve(relative_path: str) -> Path:
    """Return the absolute Path for *relative_path* under DATA_PATH."""
    return DATA_PATH / relative_path


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
    backup_path = path.with_name(f"{path.name}{_BACKUP_SUFFIX}")

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


def read_json_file(relative_path: str) -> Union[List, Dict]:
    """Read JSON from *relative_path*; returns [] on missing file or parse error."""
    path = _resolve(relative_path)

    if not path.exists():
        return []

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            logger.error(
                "Invalid JSON root in '%s' — expected a list, got %s.",
                path,
                type(data).__name__,
            )
            return []
        return data
    except json.JSONDecodeError:
        logger.error("Invalid JSON in '%s' — returning empty list.", path)
        return []
    except Exception as exc:
        logger.error("Unexpected error reading '%s': %s", path, exc)
        return []
