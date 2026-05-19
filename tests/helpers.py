from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from unittest.mock import patch


class PatchedDataPath:
    """Patch persistence modules to use an isolated temporary data root."""

    def __init__(self) -> None:
        self._tmp = TemporaryDirectory()
        self.path = Path(self._tmp.name)
        self._patches: list[Any] = []

    def __enter__(self) -> Path:
        import utils.file_manager as file_manager

        self._patches = [
            patch.object(file_manager, "DATA_PATH", self.path),
        ]
        for active_patch in self._patches:
            active_patch.start()
        return self.path

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        for active_patch in reversed(self._patches):
            active_patch.stop()
        self._tmp.cleanup()


def empty_article_storage():
    """Patch article loading so Motor construction is independent of local data."""
    return patch("shared.articles.repository.read_json_file", return_value=[])
