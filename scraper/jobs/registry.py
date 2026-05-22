from __future__ import annotations

import inspect
import logging
from typing import Any, Callable

from shared.scraping.motor import Motor

logger = logging.getLogger(__name__)

MotorFactory = Callable[..., Motor]
MotorEntry = dict[str, Any]
REQUIRED_FACTORY_PARAMETERS = ("job_id", "url", "query")


def _validate_factory_signature(provider: str, fn: MotorFactory) -> None:
    """Require provider factories to expose the shared job contract."""
    signature = inspect.signature(fn)
    missing: list[str] = []
    invalid_kind: list[str] = []

    for name in REQUIRED_FACTORY_PARAMETERS:
        parameter = signature.parameters.get(name)
        if parameter is None:
            missing.append(name)
            continue
        if parameter.kind is inspect.Parameter.POSITIONAL_ONLY:
            invalid_kind.append(name)

    if missing or invalid_kind:
        details: list[str] = []
        if missing:
            details.append(f"missing parameters: {', '.join(missing)}")
        if invalid_kind:
            details.append("must not be positional-only: " + ", ".join(invalid_kind))
        detail_text = "; ".join(details)
        raise ValueError(
            f"Factory for provider '{provider}' must declare job contract parameters "
            f"{REQUIRED_FACTORY_PARAMETERS}. Signature {signature} is invalid ({detail_text})."
        )


class MotorRegistry:
    def __init__(self) -> None:
        self._factories: dict[str, MotorFactory] = {}
        self._entries: list[MotorEntry] = []

    def factory(self, provider: str) -> Callable[[MotorFactory], MotorFactory]:
        def decorator(fn: MotorFactory) -> MotorFactory:
            _validate_factory_signature(provider, fn)
            if provider in self._factories:
                logger.warning("Overwriting existing factory for provider '%s'.", provider)
            self._factories[provider] = fn
            return fn

        return decorator

    def register(self, entry: MotorEntry) -> None:
        if "provider" not in entry:
            raise ValueError(f"Entry is missing required 'provider' key: {entry!r}")
        self._entries.append(entry)

    def register_many(self, entries: list[MotorEntry]) -> None:
        for entry in entries:
            self.register(entry)

    def clear_entries(self) -> None:
        """Remove all registered entries without touching factories."""
        self._entries.clear()

    def build(self) -> list[Motor]:
        motors: list[Motor] = []

        for entry in self._entries:
            provider = entry["provider"]
            factory = self._factories.get(provider)

            if factory is None:
                logger.error(
                    "No factory registered for provider '%s' — skipping entry: %r", provider, entry
                )
                continue

            kwargs = {k: v for k, v in entry.items() if k != "provider"}

            try:
                motor = factory(**kwargs)
                motors.append(motor)
            except Exception as exc:
                logger.error(
                    "Failed to build motor for provider '%s' with %r: %s", provider, kwargs, exc
                )

        return motors

    @property
    def providers(self) -> list[str]:
        return list(self._factories.keys())

    def __repr__(self) -> str:
        return f"MotorRegistry(providers={self.providers}, entries={len(self._entries)})"


_REGISTRY = MotorRegistry()


def register_entry(entry: MotorEntry) -> None:
    _REGISTRY.register(entry)


def register_entries(entries: list[MotorEntry]) -> None:
    _REGISTRY.register_many(entries)


def build_motors() -> list[Motor]:
    return _REGISTRY.build()
