from __future__ import annotations

import math

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class TradePlan:
    symbol: str
    direction: str
    entry: float
    stop: float
    target: float
    risk_budget: float
    setup: str
    timeframe: str = "15m"

    def __post_init__(self) -> None:
        direction = self.direction.lower()
        if direction not in {"long", "short"}:
            raise ValueError("direction must be 'long' or 'short'")
        if not all(math.isfinite(v) and v > 0 for v in (self.entry, self.stop, self.target, self.risk_budget)):
            raise ValueError("prices and risk_budget must be positive")
        if self.entry == self.stop:
            raise ValueError("entry and stop cannot be equal")
        if direction == "long" and not (self.stop < self.entry < self.target):
            raise ValueError("long plan requires stop < entry < target")
        if direction == "short" and not (self.target < self.entry < self.stop):
            raise ValueError("short plan requires target < entry < stop")

    @property
    def risk_per_share(self) -> float:
        return abs(self.entry - self.stop)

    @property
    def reward_per_share(self) -> float:
        return abs(self.target - self.entry)

    @property
    def planned_rr(self) -> float:
        return self.reward_per_share / self.risk_per_share


@dataclass(frozen=True)
class PaperTrade:
    plan: TradePlan
    exit_price: float
    quantity: float
    notes: str = ""
    desk: str = "Victor"
    timestamp: str = ""

    def __post_init__(self) -> None:
        if not math.isfinite(self.exit_price) or self.exit_price <= 0:
            raise ValueError("exit_price must be positive")
        if not math.isfinite(self.quantity) or self.quantity <= 0:
            raise ValueError("quantity must be positive")
        if not self.timestamp:
            object.__setattr__(
                self,
                "timestamp",
                datetime.now(timezone.utc).isoformat(),
            )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        return payload
