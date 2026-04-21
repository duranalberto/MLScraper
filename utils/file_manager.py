"""
utils/file_manager.py

File persistence helpers.
Supports sub-directory paths under the shared DATA_PATH root.
All callers pass a relative path such as "mercado_libre/zelda-wii.json";
this module ensures the parent directory exists before every write.
"""

import json
import asyncio
import os
from pathlib import Path
from typing import Union, List, Dict

DATA_PATH = Path("./data")


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
    path.write_text(content, encoding="utf-8")


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
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        import logging
        logging.getLogger(__name__).error(
            "Invalid JSON in '%s' — returning empty list.", path
        )
        return []
    except Exception as exc:
        import logging
        logging.getLogger(__name__).error(
            "Unexpected error reading '%s': %s", path, exc
        )
        return []