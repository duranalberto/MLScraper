"""
provider/registry.py

Declarative Motor Registry
───────────────────────────
Define every scraping job as a plain data entry.  The registry resolves each
entry into a Motor instance at runtime, hiding all constructor differences
between providers behind a uniform interface.

Design decisions
────────────────
• MotorEntry is a pure-data TypedDict — easy to read, no behaviour, no
  imports of concrete Motor classes required at definition time.
• MotorFactory (Protocol) gives type-safe extensibility: any callable that
  accepts **kwargs and returns a Motor qualifies, without inheriting from
  anything.
• MotorRegistry owns the mapping from provider names to factory functions
  and the collection of entries.  Calling .build() materialises every entry.
• _REGISTRY is the singleton instance.  register_entry() / build_motors() are
  the two public helpers used by the rest of the codebase.

Adding a new provider
─────────────────────
    1. Implement your Motor subclass as usual.
    2. Register its factory once:

        @_REGISTRY.factory("my_provider")
        def _my_provider_factory(**kwargs) -> Motor:
            return MyProvider(kwargs["search_term"], kwargs["my_option"])

    3. Add entries:

        register_entry({"provider": "my_provider", "search_term": "...", "my_option": ...})
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from scraper.motor import Motor

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

MotorFactory = Callable[..., Motor]  # (**kwargs) -> Motor
MotorEntry = dict[str, Any]          # plain data bag; "provider" key is required


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

class MotorRegistry:
    """Maps provider names → factory callables, and entries → Motor instances."""

    def __init__(self) -> None:
        self._factories: dict[str, MotorFactory] = {}
        self._entries: list[MotorEntry] = []

    # ------------------------------------------------------------------
    # Factory registration
    # ------------------------------------------------------------------

    def factory(self, provider: str) -> Callable[[MotorFactory], MotorFactory]:
        """Decorator that registers a factory under *provider* name."""
        def decorator(fn: MotorFactory) -> MotorFactory:
            if provider in self._factories:
                logger.warning("Overwriting existing factory for provider '%s'.", provider)
            self._factories[provider] = fn
            return fn
        return decorator

    # ------------------------------------------------------------------
    # Entry registration
    # ------------------------------------------------------------------

    def register(self, entry: MotorEntry) -> None:
        """Add a single entry to the registry."""
        if "provider" not in entry:
            raise ValueError(f"Entry is missing required 'provider' key: {entry!r}")
        self._entries.append(entry)

    def register_many(self, entries: list[MotorEntry]) -> None:
        """Convenience method to bulk-add entries."""
        for entry in entries:
            self.register(entry)

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def build(self) -> list[Motor]:
        """Instantiate every registered entry using its provider factory."""
        motors: list[Motor] = []

        for entry in self._entries:
            provider = entry["provider"]
            factory = self._factories.get(provider)

            if factory is None:
                logger.error(
                    "No factory registered for provider '%s' — skipping entry: %r",
                    provider,
                    entry,
                )
                continue

            # Pass all keys except "provider" as keyword arguments to the factory
            kwargs = {k: v for k, v in entry.items() if k != "provider"}

            try:
                motor = factory(**kwargs)
                motors.append(motor)
            except Exception as exc:
                logger.error(
                    "Failed to build motor for provider '%s' with %r: %s",
                    provider,
                    kwargs,
                    exc,
                )

        return motors

    # ------------------------------------------------------------------
    # Introspection helpers
    # ------------------------------------------------------------------

    @property
    def providers(self) -> list[str]:
        return list(self._factories.keys())

    def __repr__(self) -> str:
        return (
            f"MotorRegistry(providers={self.providers}, "
            f"entries={len(self._entries)})"
        )


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_REGISTRY = MotorRegistry()


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def register_entry(entry: MotorEntry) -> None:
    _REGISTRY.register(entry)


def register_entries(entries: list[MotorEntry]) -> None:
    _REGISTRY.register_many(entries)


def build_motors() -> list[Motor]:
    return _REGISTRY.build()