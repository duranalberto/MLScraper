from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "scrapper.yaml"


@dataclass(frozen=True)
class RuntimeConfig:
    backoff_initial: float
    backoff_max: float


@lru_cache(maxsize=1)
def load_runtime_config(config_path: Path | str = CONFIG_PATH) -> RuntimeConfig:
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(
            f"Scrapper config file not found: '{path.resolve()}'. "
            "Create config/scrapper.yaml to define orchestration policy values."
        )

    with path.open("r", encoding="utf-8") as fh:
        data: Any = yaml.safe_load(fh) or {}

    if not isinstance(data, dict):
        raise ValueError(f"'{path}' must contain a YAML mapping at the top level.")

    required = ("BACKOFF_INITIAL", "BACKOFF_MAX")
    missing = [key for key in required if key not in data]
    if missing:
        raise KeyError(f"Missing required scrapper config key(s) {missing!r} in '{path}'.")

    return RuntimeConfig(
        backoff_initial=int(data["BACKOFF_INITIAL"]),
        backoff_max=int(data["BACKOFF_MAX"]),
    )
