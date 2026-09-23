from __future__ import annotations

import math

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class PerformanceMetrics:
    trades: int
    wins: int
    losses: int
    breakeven: int
    win_rate: float
    average_r: float
    expectancy_r: float
    gross_positive_r: float
    gross_negative_r: float
    profit_factor: float | None
    max_drawdown_r: float
    max_winning_streak: int
    max_losing_streak: int


def _max_streak(values: list[float], *, positive: bool) -> int:
    best = 0
    current = 0
    for value in values:
        hit = value > 0 if positive else value < 0
        if hit:
            current += 1
            best = max(best, current)
        else:
            current = 0
    return best


def _max_drawdown(values: list[float]) -> float:
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    return max_dd


def performance_metrics(r_values: Iterable[float]) -> PerformanceMetrics:
    values = list(r_values)
    if not all(math.isfinite(v) for v in values):
        raise ValueError("R values must be finite")
    wins = sum(v > 0 for v in values)
    losses = sum(v < 0 for v in values)
    breakeven = sum(v == 0 for v in values)
    count = len(values)
    gross_positive = sum(v for v in values if v > 0)
    gross_negative = sum(v for v in values if v < 0)
    average = sum(values) / count if count else 0.0

    if gross_negative < 0:
        profit_factor: float | None = gross_positive / abs(gross_negative)
    elif gross_positive > 0:
        profit_factor = float("inf")
    else:
        profit_factor = None

    return PerformanceMetrics(
        trades=count,
        wins=wins,
        losses=losses,
        breakeven=breakeven,
        win_rate=(wins / count) if count else 0.0,
        average_r=average,
        expectancy_r=average,
        gross_positive_r=gross_positive,
        gross_negative_r=gross_negative,
        profit_factor=profit_factor,
        max_drawdown_r=_max_drawdown(values),
        max_winning_streak=_max_streak(values, positive=True),
        max_losing_streak=_max_streak(values, positive=False),
    )
