from __future__ import annotations

from dataclasses import dataclass, field, fields
from datetime import datetime as datetime_lib
from typing import Any, Dict, List, Optional

from .status import Status

MAX_HISTORY = 100


@dataclass
class ArticleHistory:
    datetime: str
    title: Optional[str] = None
    price: Optional[str] = None

    def __str__(self) -> str:
        return f"[{self.datetime}] - {self.title}  ${self.price}"

    def dump(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {"datetime": self.datetime}
        if self.title is not None:
            d["title"] = self.title
        if self.price is not None:
            d["price"] = self.price
        return d

    @staticmethod
    def create(args: Dict[str, Any]) -> Optional[ArticleHistory]:
        if "datetime" not in args or not args["datetime"]:
            return None
        if "title" not in args and "price" not in args:
            return None
        return ArticleHistory(
            datetime=args["datetime"],
            title=args.get("title"),
            price=args.get("price"),
        )


@dataclass
class StatusHistory:
    datetime: str
    status: Status

    def __str__(self) -> str:
        return f"[{self.datetime}] - {self.status}"

    def dump(self) -> Dict[str, Any]:
        return {
            "datetime": self.datetime,
            "status": self.status.value,
        }

    @staticmethod
    def create(args: Dict[str, Any]) -> Optional["StatusHistory"]:
        if "datetime" not in args or not args["datetime"]:
            return None
        status_value = args.get("status")
        if not status_value:
            return None
        try:
            status = status_value if isinstance(status_value, Status) else Status(status_value)
        except ValueError:
            return None
        return StatusHistory(
            datetime=args["datetime"],
            status=status,
        )


def _coerce_numeric_price(value: Any) -> Optional[float]:
    """Convert a numeric or string price into a float when possible."""
    if value is None or isinstance(value, bool):
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


@dataclass
class Article:
    identifier: str
    title: str
    price: float
    url: Optional[str] = None
    datetime: str = field(default_factory=lambda: str(datetime_lib.now()))
    status: Status = Status.none
    history: List[ArticleHistory] = field(default_factory=list)
    status_history: List[StatusHistory] = field(default_factory=list)
    hold_misses: int = 0
    last_updated: Optional[str] = None
    initial_price: Optional[float] = None
    lowest_price: Optional[float] = None
    lowest_price_at: Optional[str] = None
    highest_price: Optional[float] = None
    highest_price_at: Optional[str] = None
    last_fetched_epoch: float = 0.0
    version: int = 1
    db_id: Optional[int] = None

    def __post_init__(self) -> None:
        self.history = self._load_history(self.history)
        self.status_history = self._load_status_history(self.status_history)
        self.hold_misses = self._load_hold_misses(self.hold_misses)
        self.last_fetched_epoch = float(self.last_fetched_epoch or 0.0)
        self.version = max(1, int(self.version or 1))
        self._initialize_price_watermarks()

    def _initialize_price_watermarks(self) -> None:
        """Initialize initial, lowest, and highest price watermarks from history and current price."""
        samples: list[tuple[float, str]] = []
        for entry in reversed(self.history):
            parsed = _coerce_numeric_price(entry.price)
            if parsed is not None:
                samples.append((parsed, str(entry.datetime)))

        current_numeric = _coerce_numeric_price(self.price)
        current_ts = str(self.last_updated or self.datetime)
        if current_numeric is not None:
            samples.append((current_numeric, current_ts))

        if not samples:
            return

        if self.initial_price is None:
            self.initial_price = samples[0][0]
        else:
            coerced_init = _coerce_numeric_price(self.initial_price)
            self.initial_price = coerced_init if coerced_init is not None else samples[0][0]

        if self.lowest_price is None:
            low_price, low_ts = min(samples, key=lambda item: item[0])
            self.lowest_price = low_price
            self.lowest_price_at = self.lowest_price_at or low_ts
        else:
            coerced_low = _coerce_numeric_price(self.lowest_price)
            if coerced_low is not None:
                self.lowest_price = coerced_low
            if self.lowest_price_at is None:
                self.lowest_price_at = str(self.datetime)

        if self.highest_price is None:
            high_price, high_ts = max(samples, key=lambda item: item[0])
            self.highest_price = high_price
            self.highest_price_at = self.highest_price_at or high_ts
        else:
            coerced_high = _coerce_numeric_price(self.highest_price)
            if coerced_high is not None:
                self.highest_price = coerced_high
            if self.highest_price_at is None:
                self.highest_price_at = str(self.datetime)

    def __str__(self) -> str:
        return f"[{self.datetime}]  {self.title}  ${self.price}"

    def __repr__(self) -> str:
        return self.identifier

    def __hash__(self) -> int:
        return hash(self.identifier)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Article):
            return self.identifier == other.identifier
        return NotImplemented

    def _load_history(self, raw: list) -> List[ArticleHistory]:
        history: List[ArticleHistory] = []
        for item in raw or []:
            ah = ArticleHistory.create(item)
            if ah:
                history.append(ah)

        return history

    def _load_status_history(self, raw: list) -> List[StatusHistory]:
        history: List[StatusHistory] = []
        for item in raw or []:
            ah = StatusHistory.create(item)
            if ah:
                history.append(ah)
        return history

    @staticmethod
    def _load_hold_misses(value: Any) -> int:
        if value is None:
            return 0
        try:
            misses = int(value)
        except TypeError, ValueError:
            return 0
        return max(0, misses)

    def update(self, to_update: Dict[str, Any]) -> bool:
        """
        Apply title/price changes and record them in history.
        Returns True if any field actually changed.
        """
        keys = ("title", "price")
        changes = {
            k: to_update[k] for k in keys if k in to_update and getattr(self, k) != to_update[k]
        }

        if not changes:
            return False

        old_values = {k: getattr(self, k) for k in changes}
        original_datetime = self.datetime
        previous_last_updated = self.last_updated

        for k, v in changes.items():
            setattr(self, k, v)

        is_first = not self.history
        history_entry = {
            **old_values,
            "datetime": (
                original_datetime
                if is_first or previous_last_updated is None
                else previous_last_updated
            ),
        }
        ah = ArticleHistory.create(history_entry)
        if ah:
            self.last_updated = str(datetime_lib.now())
            self.history.insert(0, ah)
            self.history = self.history[:MAX_HISTORY]

        self.version += 1
        if "price" in changes:
            new_numeric = _coerce_numeric_price(self.price)
            update_ts = str(self.last_updated or self.datetime)
            if new_numeric is not None:
                if self.initial_price is None:
                    old_numeric = _coerce_numeric_price(old_values.get("price"))
                    self.initial_price = old_numeric if old_numeric is not None else new_numeric
                if self.lowest_price is None or new_numeric < self.lowest_price:
                    self.lowest_price = new_numeric
                    self.lowest_price_at = update_ts
                if self.highest_price is None or new_numeric > self.highest_price:
                    self.highest_price = new_numeric
                    self.highest_price_at = update_ts

        return True

    def record_status_history(self, status: Status) -> bool:
        """
        Record lifecycle transitions that matter to the hold/finish flow.
        We intentionally never persist `on_hold` here.
        Consecutive duplicate statuses are ignored to avoid noisy history
        when a lifecycle transition is replayed.
        """
        if status == Status.on_hold:
            return False
        if self.status_history and self.status_history[0].status == status:
            return False

        ah = StatusHistory.create(
            {
                "datetime": str(datetime_lib.now()),
                "status": status.value,
            }
        )
        if not ah:
            return False

        self.status_history.insert(0, ah)
        self.status_history = self.status_history[:MAX_HISTORY]
        return True

    def dump(self) -> Dict[str, Any]:
        """
        Serialise to a dict suitable for JSON storage.
        `job_id` is intentionally omitted — it belongs to the Motor,
        not to individual articles.
        """
        d: Dict[str, Any] = {
            "identifier": self.identifier,
            "title": self.title,
            "price": self.price,
            "url": self.url,
            "datetime": str(self.datetime),
            "status": self.status.value,
        }
        if self.history:
            d["last_updated"] = self.last_updated
            d["history"] = [ah.dump() for ah in self.history]
        if self.status_history:
            d["status_history"] = [ah.dump() for ah in self.status_history]
        if self.hold_misses:
            d["hold_misses"] = self.hold_misses
        return d

    @staticmethod
    def is_valid_args(args: Dict[str, Any]) -> bool:
        # Required fields (no default): identifier, title, price
        required = {"identifier", "title", "price"}
        return required.issubset(args.keys())

    @staticmethod
    def create(args: Dict[str, Any]) -> Optional[Article]:
        if not Article.is_valid_args(args):
            return None
        known = {f.name for f in fields(Article)}
        return Article(**{k: v for k, v in args.items() if k in known})
