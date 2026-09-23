from __future__ import annotations

import argparse
from pathlib import Path

from .backtest import load_ohlc_csv, resolve_plan
from .journal import load_trades
from .metrics import performance_metrics
from .models import TradePlan
from .risk import position_size


def _plan(args: argparse.Namespace) -> None:
    plan = TradePlan(
        symbol=args.symbol,
        direction=args.direction,
        entry=args.entry,
        stop=args.stop,
        target=args.target,
        risk_budget=args.risk,
        setup=args.setup,
        timeframe=args.timeframe,
    )
    qty = position_size(plan, fractional=args.fractional)
    print(f"{plan.symbol} {plan.direction.upper()}")
    print(f"Risk/share: {plan.risk_per_share:.4f}")
    print(f"Reward/share: {plan.reward_per_share:.4f}")
    print(f"Planned R:R: 1:{plan.planned_rr:.2f}")
    print(f"Quantity: {qty:g}")
    print(f"Cash risk: {qty * plan.risk_per_share:.2f}")


def _stats(args: argparse.Namespace) -> None:
    from .risk import realized_r

    trades = load_trades(args.journal)
    metrics = performance_metrics(realized_r(t) for t in trades)
    print(metrics)


def _resolve(args: argparse.Namespace) -> None:
    plan = TradePlan(
        symbol=args.symbol,
        direction=args.direction,
        entry=args.entry,
        stop=args.stop,
        target=args.target,
        risk_budget=args.risk,
        setup=args.setup,
        timeframe=args.timeframe,
    )
    candles = load_ohlc_csv(args.csv)
    outcome = resolve_plan(plan, candles, ambiguous_policy=args.ambiguous)
    print(outcome)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sc-rd", description="SC Trading R&D paper research tools")
    subs = parser.add_subparsers(dest="command", required=True)

    p = subs.add_parser("plan", help="calculate paper-trade position size and R:R")
    p.add_argument("symbol")
    p.add_argument("direction", choices=["long", "short"])
    p.add_argument("entry", type=float)
    p.add_argument("stop", type=float)
    p.add_argument("target", type=float)
    p.add_argument("risk", type=float)
    p.add_argument("--setup", default="manual")
    p.add_argument("--timeframe", default="15m")
    p.add_argument("--fractional", action="store_true")
    p.set_defaults(func=_plan)

    p = subs.add_parser("stats", help="summarize a JSONL paper-trade journal")
    p.add_argument("journal", type=Path)
    p.set_defaults(func=_stats)

    p = subs.add_parser("resolve", help="resolve a fixed paper-trade plan against OHLC CSV data")
    p.add_argument("csv", type=Path)
    p.add_argument("symbol")
    p.add_argument("direction", choices=["long", "short"])
    p.add_argument("entry", type=float)
    p.add_argument("stop", type=float)
    p.add_argument("target", type=float)
    p.add_argument("risk", type=float)
    p.add_argument("--setup", default="manual")
    p.add_argument("--timeframe", default="15m")
    p.add_argument("--ambiguous", choices=["conservative", "optimistic", "skip"], default="conservative")
    p.set_defaults(func=_resolve)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
