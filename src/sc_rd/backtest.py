from __future__ import annotations

import math

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Literal

from .models import TradePlan


AmbiguousPolicy = Literal["conservative", "optimistic", "skip"]


@dataclass(frozen=True)
class Candle:
    timestamp: str
    open: float
    high: float
    low: float
    close: float

    def __post_init__(self) -> None:
        if not all(math.isfinite(v) and v > 0 for v in (self.open, self.high, self.low, self.close)):
            raise ValueError("OHLC values must be positive")
        if self.low > self.high:
            raise ValueError("candle low cannot be above high")
        if not (self.low <= self.open <= self.high):
            raise ValueError("open must sit inside candle range")
        if not (self.low <= self.close <= self.high):
            raise ValueError("close must sit inside candle range")


@dataclass(frozen=True)
class BacktestOutcome:
    status: str
    exit_price: float | None
    realized_r: float | None
    exit_timestamp: str | None
    candles_seen: int
    note: str = ""


def load_ohlc_csv(path: str | Path) -> list[Candle]:
    rows: list[Candle] = []
    with Path(path).open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"timestamp", "open", "high", "low", "close"}
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            missing = required.difference(reader.fieldnames or [])
            raise ValueError(f"CSV missing required columns: {sorted(missing)}")
        for row in reader:
            rows.append(
                Candle(
                    timestamp=row["timestamp"],
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                )
            )
    return rows


def _r_from_exit(plan: TradePlan, exit_price: float) -> float:
    move = exit_price - plan.entry
    if plan.direction.lower() == "short":
        move *= -1
    return move / plan.risk_per_share


def resolve_plan(
    plan: TradePlan,
    candles: Iterable[Candle],
    *,
    ambiguous_policy: AmbiguousPolicy = "conservative",
) -> BacktestOutcome:
    """Resolve a pre-defined paper trade against OHLC candles.

    This intentionally does not infer an entry signal. It evaluates a plan after
    entry, keeping strategy logic separate from fill/exit assumptions.

    When stop and target are both touched inside the same OHLC candle, sequence
    is unknowable without lower-timeframe data. The policy makes that ambiguity
    explicit instead of pretending the backtest knows the path.
    """
    if ambiguous_policy not in {"conservative", "optimistic", "skip"}:
        raise ValueError("unsupported ambiguous_policy")

    direction = plan.direction.lower()
    index = 0
    for index, candle in enumerate(candles, start=1):
        # The open is the first known price; stop orders can lose more than 1R.
        gap_stop = candle.open <= plan.stop if direction == "long" else candle.open >= plan.stop
        gap_target = candle.open >= plan.target if direction == "long" else candle.open <= plan.target
        if gap_stop or gap_target:
            price = candle.open if gap_stop else plan.target
            return BacktestOutcome(
                status="stop" if gap_stop else "target",
                exit_price=price,
                realized_r=_r_from_exit(plan, price),
                exit_timestamp=candle.timestamp,
                candles_seen=index,
                note="opening stop fill" if gap_stop else "opening target fill; no price improvement assumed",
            )
        if direction == "long":
            hit_stop = candle.low <= plan.stop
            hit_target = candle.high >= plan.target
        else:
            hit_stop = candle.high >= plan.stop
            hit_target = candle.low <= plan.target

        if hit_stop and hit_target:
            if ambiguous_policy == "skip":
                return BacktestOutcome(
                    status="ambiguous",
                    exit_price=None,
                    realized_r=None,
                    exit_timestamp=candle.timestamp,
                    candles_seen=index,
                    note="stop and target touched in same candle; path unknown",
                )
            exit_price = plan.stop if ambiguous_policy == "conservative" else plan.target
            label = "stop" if ambiguous_policy == "conservative" else "target"
            return BacktestOutcome(
                status=label,
                exit_price=exit_price,
                realized_r=_r_from_exit(plan, exit_price),
                exit_timestamp=candle.timestamp,
                candles_seen=index,
                note="same-candle ambiguity resolved by explicit policy",
            )

        if hit_stop:
            return BacktestOutcome(
                status="stop",
                exit_price=plan.stop,
                realized_r=_r_from_exit(plan, plan.stop),
                exit_timestamp=candle.timestamp,
                candles_seen=index,
            )

        if hit_target:
            return BacktestOutcome(
                status="target",
                exit_price=plan.target,
                realized_r=_r_from_exit(plan, plan.target),
                exit_timestamp=candle.timestamp,
                candles_seen=index,
            )

    return BacktestOutcome(
        status="open",
        exit_price=None,
        realized_r=None,
        exit_timestamp=None,
        candles_seen=index,
        note="neither stop nor target reached in supplied candles",
    )
