"""Causal rolling-range breakout signals and next-open paper simulation."""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass

from .backtest import Candle, resolve_plan
from .desks import DESKS
from .models import TradePlan
from .research import Costs, summary
from .risk import position_size


@dataclass(frozen=True)
class Breakout:
    name: str
    desk: str
    lookback: int
    reward_r: float
    max_holding_bars: int
    direction: str = "both"

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("strategy name is required")
        if self.desk not in DESKS:
            raise ValueError("unknown research desk")
        for value in (self.lookback, self.max_holding_bars):
            if type(value) is not int or value < 1:
                raise ValueError("lookback and max_holding_bars must be positive integers")
        if isinstance(self.reward_r, bool) or not isinstance(self.reward_r, (int, float)) or not math.isfinite(self.reward_r) or self.reward_r <= 0:
            raise ValueError("reward_r must be finite and positive")
        if self.direction not in {"both", "long", "short"}:
            raise ValueError("direction must be both, long or short")


@dataclass(frozen=True)
class Signal:
    index: int
    timestamp: str
    direction: str
    stop: float


def signal_at(candles: list[Candle], index: int, strategy: Breakout) -> Signal | None:
    """Read only the signal candle and its preceding lookback candles."""
    if index < 0 or index >= len(candles):
        raise ValueError("signal index outside dataset")
    if index < strategy.lookback:
        return None
    prior = candles[index - strategy.lookback:index]
    high, low = max(c.high for c in prior), min(c.low for c in prior)
    current = candles[index]
    if current.close > high and strategy.direction in {"both", "long"}:
        return Signal(index, current.timestamp, "long", low)
    if current.close < low and strategy.direction in {"both", "short"}:
        return Signal(index, current.timestamp, "short", high)
    return None


def simulate(candles: list[Candle], strategy: Breakout, start: int, end: int, *,
             symbol: str, risk_budget: float, costs: Costs,
             ambiguous_policy: str = "conservative", minimum_trades: int = 1) -> dict:
    """Simulate entries in [start, end), with past-only warmup and no carry."""
    if not (0 <= start < end <= len(candles)):
        raise ValueError("invalid simulation window")
    if isinstance(risk_budget, bool) or not math.isfinite(risk_budget) or risk_budget <= 0:
        raise ValueError("risk_budget must be finite and positive")
    if ambiguous_policy not in {"conservative", "optimistic", "skip"}:
        raise ValueError("unsupported ambiguous_policy")
    rows, skipped = [], []
    entry_index = max(start, strategy.lookback + 1)
    while entry_index < end:
        signal = signal_at(candles, entry_index - 1, strategy)
        if signal is None:
            entry_index += 1
            continue
        entry = candles[entry_index].open  # Never entry candle high/low/close.
        distance = entry - signal.stop if signal.direction == "long" else signal.stop - entry
        target = entry + strategy.reward_r * distance if signal.direction == "long" else entry - strategy.reward_r * distance
        if distance <= 0 or target <= 0 or not math.isfinite(target):
            skipped.append({"signal": asdict(signal), "entry_index": entry_index,
                            "reason": "next open invalidates stop or positive-price target"})
            entry_index += 1
            continue
        plan = TradePlan(symbol, signal.direction, entry, signal.stop, target, risk_budget,
                         setup="rolling-range-breakout", timeframe="dataset-bars")
        quantity = position_size(plan)
        if not math.isfinite(quantity) or quantity <= 0:
            raise ValueError("position size must be finite and positive")
        deadline = entry_index + strategy.max_holding_bars
        outcome = resolve_plan(plan, candles[entry_index:min(end, deadline)], ambiguous_policy=ambiguous_policy)
        exit_index = entry_index + outcome.candles_seen - 1
        status, exit_price, note = outcome.status, outcome.exit_price, outcome.note
        if status == "open" and deadline <= end:
            status = "timeout"
            exit_price = candles[exit_index].close
            note = "maximum holding period reached; exit at final bar close"
        gross_r = None
        cost = None
        net_r = None
        if exit_price is not None:
            gross_r = (exit_price - entry) / distance * (1 if signal.direction == "long" else -1)
            cost = costs.round_trip(entry, exit_price, quantity)
            net_r = gross_r - cost / (distance * quantity)
            if not math.isfinite(net_r):
                raise ValueError("net R calculation overflow")
        rows.append({"signal": asdict(signal), "entry_index": entry_index,
                     "entry_at": candles[entry_index].timestamp, "plan": asdict(plan),
                     "quantity": quantity, "status": status, "exit_price": exit_price,
                     "exit_index": exit_index if exit_price is not None else None,
                     "exit_timestamp": candles[exit_index].timestamp if exit_price is not None else None,
                     "candles_seen": outcome.candles_seen, "gross_r": gross_r,
                     "round_trip_cost": cost, "net_r": net_r, "note": note})
        if status in {"open", "ambiguous"}:
            # Unknown exposure cannot support another independent entry.
            break
        entry_index = exit_index + 1
    return {"strategy": asdict(strategy), "start": start, "end_exclusive": end,
            "summary": summary(rows, minimum_trades), "trades": rows, "skipped_entries": skipped}
