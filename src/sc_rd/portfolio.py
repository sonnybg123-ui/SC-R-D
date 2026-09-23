"""Deterministic multi-strategy, shared-cash replay on synchronized local bars."""
from __future__ import annotations

import json
import math
from collections import Counter
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path

from .models import TradePlan
from .paper import Limits, PaperBroker, number
from .research import Costs, canonical, digest, engine_fingerprint, fields, read_dataset, summary
from .strategy import Breakout, signal_at


def prepare(config: dict, base: Path, period: str) -> tuple:
    config = json.loads(canonical(config))
    fields(config, {"schema_version", "datasets", "initial_cash", "costs", "limits", "holdout_bars",
                    "end_policy", "minimum_trades", "experiments"}, "portfolio replay")
    if type(config["schema_version"]) is not int or config["schema_version"] != 1:
        raise ValueError("unsupported schema_version")
    if period not in {"development", "holdout"}:
        raise ValueError("period must be development or holdout")
    for key in ("holdout_bars", "minimum_trades"):
        if type(config[key]) is not int or config[key] < 1:
            raise ValueError(f"{key} must be a positive integer")
    if config["end_policy"] not in {"keep_open", "liquidate"}:
        raise ValueError("end_policy must be keep_open or liquidate")
    number(config["initial_cash"])
    fields(config["limits"], set(asdict(Limits())), "limits")
    fields(config["costs"], {"fee_per_side", "fee_bps", "spread_bps", "slippage_bps"}, "costs")
    Limits(**config["limits"])
    costs = Costs(**config["costs"])
    if costs.fee_bps + costs.spread_bps / 2 + costs.slippage_bps >= 10000:
        raise ValueError("combined per-side cost rate must be below 100%")
    if not isinstance(config["datasets"], dict) or not config["datasets"]:
        raise ValueError("nonempty symbol-to-CSV dataset mapping required")
    data, hashes, grid = {}, {}, None
    for symbol, location in sorted(config["datasets"].items()):
        if not isinstance(symbol, str) or not symbol.strip():
            raise ValueError("nonempty symbol required")
        candles, times, fingerprint = read_dataset(base / location)
        if grid is not None and grid != times:
            raise ValueError("all datasets must share an identical UTC timestamp grid")
        for candle in candles:
            for price in (candle.open, candle.high, candle.low, candle.close):
                number(price)
        grid, data[symbol], hashes[symbol] = times, candles, fingerprint
    cutoff = len(grid) - config["holdout_bars"]
    if cutoff < 2:
        raise ValueError("reserve a nonempty holdout and at least two development bars")
    experiments = config["experiments"]
    if not isinstance(experiments, list) or not experiments:
        raise ValueError("nonempty experiments required")
    names = set()
    for experiment in experiments:
        fields(experiment, {"name", "allocations"}, "experiment")
        name = experiment["name"]
        if not isinstance(name, str) or not name.strip() or name in names:
            raise ValueError("experiment names must be nonempty and unique")
        names.add(name)
        allocations = experiment["allocations"]
        if not isinstance(allocations, list) or not allocations:
            raise ValueError("nonempty allocations required")
        ids, priorities = set(), set()
        for allocation in allocations:
            fields(allocation, {"id", "symbol", "priority", "risk_budget", "strategy"}, "allocation")
            identifier = allocation["id"]
            if not isinstance(identifier, str) or not (1 <= len(identifier) <= 40) or not all(c.isascii() and (c.isalnum() or c in "-_") for c in identifier) or identifier in ids:
                raise ValueError("allocation IDs must be unique, 1-40 ASCII letters/digits/hyphens/underscores")
            priority = allocation["priority"]
            if type(priority) is not int or priority < 0 or priority in priorities:
                raise ValueError("allocation priorities must be unique nonnegative integers")
            if allocation["symbol"] not in data:
                raise ValueError("allocation symbol missing from datasets")
            number(allocation["risk_budget"])
            Breakout(**allocation["strategy"])
            ids.add(identifier)
            priorities.add(priority)
    start, end = (0, cutoff) if period == "development" else (cutoff, len(grid))
    method = dict(config)
    method["datasets"] = sorted(data)  # Paths are locations, not research assumptions.
    identity = {"kind": "shared-cash-replay-v1", "datasets": hashes,
                "config": digest(canonical(method).encode()), "engine": engine_fingerprint(), "period": period}
    return config, data, grid, start, end, method, identity


def replay_experiment(config: dict, experiment: dict, data: dict, grid: list,
                      start: int, end: int, database: Path) -> dict:
    broker = PaperBroker.create(database, initial_cash=config["initial_cash"], costs=Costs(**config["costs"]),
                               limits=Limits(**config["limits"]), at=grid[start].isoformat())
    allocations = sorted(experiment["allocations"], key=lambda a: a["priority"])
    strategies = {a["id"]: Breakout(**a["strategy"]) for a in allocations}
    active, ownership = {}, {}
    orders, exits, curve = [], [], []

    def capture(index, phase):
        snap = broker.snapshot()
        curve.append({"bar_index": index, "at": grid[index].isoformat(), "phase": phase,
                      "balances": snap["balances"], "open_positions": len(snap["state"]["positions"]),
                      "halted": snap["state"]["halted"], "risk_flags": snap["risk_flags"]})

    def close(pid, price, i, phase, reason):
        result = broker.close(pid, price, command_id=f"{phase}-{i}-{active[pid]['allocation_id']}",
                              at=grid[i].isoformat(), reason=reason)
        if result["status"] != "closed":
            raise ValueError("replay lost ownership of an open position")
        exits.append({"bar_index": i, "phase": phase, "allocation_id": active[pid]["allocation_id"], **result})
        del active[pid]

    for i in range(start, end):
        at = grid[i].isoformat()
        effective_opens = {symbol: candles[i].open for symbol, candles in data.items()}
        gaps = []
        for pid, holding in sorted(active.items()):
            p = holding["position"]
            op = Decimal(str(data[p["symbol"]][i].open))
            stop, target = Decimal(p["stop"]), Decimal(p["target"])
            is_long = p["direction"] == "long"
            if (op <= stop if is_long else op >= stop):
                gaps.append((pid, str(op), "replay-opening-gap-stop"))
            elif (op >= target if is_long else op <= target):
                gaps.append((pid, str(target), "replay-opening-target"))
                # Do not mark profits at an open better than the capped target fill.
                effective_opens[p["symbol"]] = str(target)
        broker.mark(effective_opens, command_id=f"open-marks-{i}", at=at)
        for pid, price, reason in gaps:
            close(pid, price, i, "gap", reason)
        capture(i, "open")

        # Only t-1 and earlier are read for all entries; no current H/L/C yet.
        for allocation in allocations:
            if i == 0:
                continue
            symbol, aid = allocation["symbol"], allocation["id"]
            spec = strategies[aid]
            signal = signal_at(data[symbol], i - 1, spec)
            if signal is None:
                continue
            entry = data[symbol][i].open
            distance = entry - signal.stop if signal.direction == "long" else signal.stop - entry
            target = entry + spec.reward_r * distance if signal.direction == "long" else entry - spec.reward_r * distance
            item = {"bar_index": i, "at": at, "allocation_id": aid, "priority": allocation["priority"],
                    "symbol": symbol, "signal": asdict(signal)}
            if distance <= 0 or target <= 0 or not math.isfinite(target):
                orders.append(item | {"status": "skipped", "reason": "next open invalidates stop or target"})
                continue
            plan = TradePlan(symbol, signal.direction, entry, signal.stop, target, float(allocation["risk_budget"]),
                             setup=f"allocation:{aid}/rolling-range-breakout", timeframe="dataset-bars")
            pid = f"entry-{i}-{aid}"
            result = broker.open(plan, command_id=pid, at=at, desk=spec.desk)
            orders.append(item | result)
            if result["status"] == "filled":
                active[pid] = {"allocation_id": aid, "position": result["position"],
                               "deadline": i + spec.max_holding_bars - 1}
                ownership[pid] = aid
        capture(i, "entries")

        # All admissions are complete before any intrabar profit becomes available.
        batch = broker.process_bars({s: bars[i] for s, bars in data.items()}, command_id=f"close-bars-{i}")
        if batch["status"] != "processed":
            raise ValueError("replay bar batch unexpectedly rejected")
        for result in batch["bars"].values():
            for exit_result in result["exits"]:
                pid = exit_result["trade"]["position_id"]
                exits.append({"bar_index": i, "phase": "intrabar", "allocation_id": active[pid]["allocation_id"], **exit_result})
                del active[pid]
        for pid, holding in list(sorted(active.items())):
            if i >= holding["deadline"]:
                close(pid, data[holding["position"]["symbol"]][i].close, i, "timeout", "replay-timeout")
        if i == end - 1 and config["end_policy"] == "liquidate":
            for pid, holding in list(sorted(active.items())):
                close(pid, data[holding["position"]["symbol"]][i].close, i, "end", "replay-end")
        capture(i, "close")

    final = PaperBroker(database).snapshot()
    if set(final["state"]["positions"]) != set(active):
        raise ValueError("coordinator and ledger position reconciliation failed")
    attribution = []
    for allocation in allocations:
        aid = allocation["id"]
        rows = [{"net_r": float(t["net_r"]), "status": "closed"} for t in final["state"]["closed"]
                if ownership[t["position_id"]] == aid]
        rows += [{"net_r": None, "status": "open"} for p in active.values() if p["allocation_id"] == aid]
        attribution.append({"allocation_id": aid, "desk": allocation["strategy"]["desk"],
                            "summary": summary(rows, config["minimum_trades"])})
    pending = []
    for allocation in allocations:
        signal = signal_at(data[allocation["symbol"]], end - 1, strategies[allocation["id"]])
        if signal is not None:
            pending.append({"allocation_id": allocation["id"], "signal": asdict(signal),
                            "reason": "no next open inside the selected period"})
    return {"name": experiment["name"], "ledger_file": database.name, "start_index": start, "end_exclusive": end,
            "orders": orders, "exits": exits, "equity_curve": curve, "attribution": attribution,
            "unfilled_final_signals": pending, "order_counts": dict(Counter(o["status"] for o in orders)),
            "rejection_reasons": dict(Counter(o["reason"] for o in orders if o["status"] in {"rejected", "skipped"})),
            "max_sampled_drawdown": str(max(Decimal(p["balances"]["drawdown"]) for p in curve)), "final": final}


def report(result: dict) -> str:
    def clean(value):
        return str(value).replace("|", "\\|").replace("\n", " ").replace("\r", " ")
    lines = ["# SC Trading R&D shared-cash replay", "", "Offline paper research only. Synthetic fixtures are wiring checks, not market evidence.", "",
             f"Run: `{result['run_id']}`", f"Engine: `{result['identity']['engine']}`",
             f"Configuration: `{result['identity']['config']}`", f"Period: **{result['period']}**. Holdout: **{result['holdout_status']}**.",
             f"End policy: `{result['method']['end_policy']}`.", "",
             "| Portfolio | Closed | Open | Rejected | Final cash | Final equity | Realized net P&L | Max sampled drawdown |",
             "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for trial in result["experiments"]:
        state, book = trial["final"]["state"], trial["final"]["balances"]
        lines.append(f"| {clean(trial['name'])} | {len(state['closed'])} | {len(state['positions'])} | {trial['order_counts'].get('rejected', 0)} | {book['cash']} | {book['equity']} | {book['realized_net_pnl']} | {trial['max_sampled_drawdown']} |")
    lines += ["", "Dataset SHA-256 fingerprints:", ""]
    lines.extend(f"- {clean(symbol)}: `{fingerprint}`" for symbol, fingerprint in result["identity"]["datasets"].items())
    lines += ["", "## Allocation outcomes and rejections", ""]
    for trial in result["experiments"]:
        lines += [f"### {clean(trial['name'])}", "", f"Ledger: `{trial['ledger_file']}`; verified head `{trial['final']['ledger_head']}`.", ""]
        for a in trial["attribution"]:
            stats = a["summary"]
            mean = f"{stats['net_metrics']['average_r']:.4f}" if stats["closed"] else "N/A"
            lines.append(f"- {clean(a['allocation_id'])} / {clean(a['desk'])}: {stats['closed']} closed, {stats['open']} open, mean net R {mean}.")
            lines.extend(f"  - {warning}" for warning in stats["warnings"])
        for reason, count in trial["rejection_reasons"].items():
            lines.append(f"- {count} rejected/skipped: {clean(reason)}.")
        lines.append(f"- Final signals without a next open: {len(trial['unfilled_final_signals'])}.")
        lines.extend(f"- Risk flag: {clean(flag)}." for flag in trial["final"]["risk_flags"])
    lines += ["", "## Timing and limits", "",
              "All datasets must have an identical UTC timestamp grid. No interpolation or future-value filling is performed.",
              "At each open, mark known prices atomically and settle existing opening gaps. Admit prior-close signals by ascending frozen allocation priority. All entries finish before any same-candle intrabar proceeds are available.",
              "Resolve all symbols' OHLC bars in one atomic broker event, then close timed-out positions. Stops win same-candle ambiguity. End liquidation, if selected, uses the last included close and charges costs.",
              "Allocations inside one portfolio share cash, collateral, risk caps and a drawdown halt. Separate portfolio experiments start with identical assumptions but independent cash. One position per symbol applies even across desks.",
              "Retained open positions contribute to equity but not closed-trade metrics. Drawdown is sampled at replay phases, not an inferred intrabar path. Priority is a research assumption and can materially change which desk gets capacity.",
              "Development excludes the reserved final bars. A holdout run starts flat and uses earlier bars only for signal warmup; viewing it consumes the holdout. No automatic model selection or live promotion is performed.",
              "No market edge, statistical confidence, continuous-market liquidity, or guaranteed loss cap is implied. Costs and gaps can exhaust synthetic collateral. Reports do not authorize broker access.", ""]
    return "\n".join(lines)


def run_portfolio(config_path: str | Path, output_dir: str | Path, *, period: str = "development") -> Path:
    path = Path(config_path)
    prepared = prepare(json.loads(path.read_text(encoding="utf-8")), path.resolve().parent, period)
    config, data, grid, start, end, method, identity = prepared
    run_id = digest(canonical(identity).encode())
    destination = Path(output_dir) / run_id
    destination.mkdir(parents=True, exist_ok=False)
    manifest = {"status": "running", "run_id": run_id, "identity": identity}

    def save_manifest():
        (destination / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    save_manifest()
    try:
        trials = [replay_experiment(config, trial, data, grid, start, end, destination / f"portfolio-{i:03d}.db")
                  for i, trial in enumerate(config["experiments"])]
        result = {"mode": "paper-research-only", "schema_version": 1, "run_id": run_id,
                  "identity": identity, "method": method, "period": period,
                  "holdout_status": "withheld" if period == "development" else "consumed-do-not-retune",
                  "experiments": trials}
        (destination / "results.json").write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
        (destination / "report.md").write_text(report(result), encoding="utf-8")
        manifest["status"] = "complete"
        save_manifest()
    except Exception:
        manifest["status"] = "failed"
        try:
            save_manifest()
        except OSError:
            pass
        raise
    return destination
