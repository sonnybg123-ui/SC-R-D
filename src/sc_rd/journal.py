from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .models import PaperTrade, TradePlan
from .risk import realized_r


@dataclass(frozen=True)
class JournalStats:
    trades: int
    wins: int
    losses: int
    breakeven: int
    win_rate: float
    average_r: float
    expectancy_r: float
    gross_positive_r: float
    gross_negative_r: float


def append_trade(path: str | Path, trade: PaperTrade) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    record = trade.to_dict() | {"realized_r": realized_r(trade)}
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, separators=(",", ":"), allow_nan=False) + "\n")


def load_trades(path: str | Path) -> list[PaperTrade]:
    target = Path(path)
    if not target.exists():
        return []
    trades: list[PaperTrade] = []
    for line in target.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        plan = TradePlan(**row["plan"])
        trades.append(
            PaperTrade(
                plan=plan,
                exit_price=row["exit_price"],
                quantity=row["quantity"],
                notes=row.get("notes", ""),
                desk=row.get("desk", "Victor"),
                timestamp=row.get("timestamp", ""),
            )
        )
    return trades


def summarize(trades: Iterable[PaperTrade]) -> JournalStats:
    r_values = [realized_r(t) for t in trades]
    wins = sum(r > 0 for r in r_values)
    losses = sum(r < 0 for r in r_values)
    breakeven = sum(r == 0 for r in r_values)
    count = len(r_values)
    average_r = sum(r_values) / count if count else 0.0
    return JournalStats(
        trades=count,
        wins=wins,
        losses=losses,
        breakeven=breakeven,
        win_rate=(wins / count) if count else 0.0,
        average_r=average_r,
        expectancy_r=average_r,
        gross_positive_r=sum(r for r in r_values if r > 0),
        gross_negative_r=sum(r for r in r_values if r < 0),
    )
