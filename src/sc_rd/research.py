"""Deterministic, offline evaluation of frozen paper-trade plans."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from .backtest import Candle, resolve_plan
from .desks import DESKS
from .metrics import performance_metrics
from .models import TradePlan
from .risk import position_size


def canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def instant(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("timestamps must include a timezone")
    return result.astimezone(timezone.utc)


def fields(value: dict, expected: set[str], label: str) -> None:
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError(f"{label} requires exactly these fields: {sorted(expected)}")


@dataclass(frozen=True)
class Costs:
    """All amounts use the same currency as OHLC. Rates are basis points."""
    fee_per_side: float
    fee_bps: float
    spread_bps: float
    slippage_bps: float

    def __post_init__(self) -> None:
        for value in asdict(self).values():
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise ValueError("costs must be finite, nonnegative numbers")

    def round_trip(self, entry: float, exit_price: float, quantity: float) -> float:
        # Half the quoted spread and full slippage/fee rate on each side.
        notional = (entry + exit_price) * quantity
        result = 2 * self.fee_per_side + notional * (self.fee_bps + self.spread_bps / 2 + self.slippage_bps) / 10000
        if not math.isfinite(result):
            raise ValueError("cost calculation overflow")
        return result


def read_dataset(path: Path) -> tuple[list[Candle], list[datetime], str]:
    raw = path.read_bytes()  # Hash exactly the bytes parsed, with no second read.
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
    if not reader.fieldnames or len(reader.fieldnames) != 5 or set(reader.fieldnames) != {"timestamp", "open", "high", "low", "close"}:
        raise ValueError("dataset requires timestamp, open, high, low, close columns")
    candles = []
    for row in reader:
        if None in row or any(v is None for v in row.values()):
            raise ValueError("malformed CSV row")
        candles.append(Candle(row["timestamp"], *(float(row[k]) for k in ("open", "high", "low", "close"))))
    times = [instant(c.timestamp) for c in candles]
    if len(times) < 2 or any(a >= b for a, b in zip(times, times[1:])):
        raise ValueError("dataset needs at least two strictly chronological, unique candles")
    return candles, times, digest(raw)


def engine_fingerprint() -> str:
    root = Path(__file__).parent
    # Include all package modules, including fill and validation dependencies.
    manifest = {p.relative_to(root).as_posix(): digest(p.read_bytes()) for p in sorted(root.rglob("*.py"))}
    return digest(canonical(manifest).encode())


def summary(rows: list[dict], minimum: int) -> dict:
    closed = [r for r in rows if r["net_r"] is not None]
    metrics = asdict(performance_metrics(r["net_r"] for r in closed))
    if metrics["profit_factor"] is not None and math.isinf(metrics["profit_factor"]):
        metrics["profit_factor"] = "infinite"
    warnings = []
    if len(closed) < minimum:
        warnings.append(f"Only {len(closed)} closed trades; minimum reporting threshold is {minimum}. This threshold is not statistical confidence.")
    unresolved = len(rows) - len(closed)
    if unresolved:
        warnings.append(f"{unresolved} open/ambiguous trades excluded from metrics; exclusion can bias results.")
    return {"submitted": len(rows), "closed": len(closed),
            "open": sum(r["status"] == "open" for r in rows),
            "ambiguous": sum(r["status"] == "ambiguous" for r in rows),
            "net_metrics": metrics, "warnings": warnings}


def evaluate(config: dict, base_dir: Path) -> dict:
    """Evaluate independent, non-overlapping plans per experiment; never place orders."""
    # Snapshot and validate JSON before evaluation, rejecting NaN and infinity.
    config = json.loads(canonical(config))
    fields(config, {"schema_version", "dataset", "symbol", "split_at", "costs", "ambiguous_policy", "minimum_trades", "experiments"}, "batch")
    if type(config["schema_version"]) is not int or config["schema_version"] != 1:
        raise ValueError("unsupported schema_version")
    if not isinstance(config["symbol"], str) or not config["symbol"].strip():
        raise ValueError("symbol is required")
    if config["ambiguous_policy"] not in {"conservative", "optimistic", "skip"}:
        raise ValueError("unsupported ambiguous_policy")
    minimum = config["minimum_trades"]
    if type(minimum) is not int or minimum < 1:
        raise ValueError("minimum_trades must be a positive integer")
    fields(config["costs"], {"fee_per_side", "fee_bps", "spread_bps", "slippage_bps"}, "costs")
    costs = Costs(**config["costs"])
    candles, times, data_hash = read_dataset(base_dir / config["dataset"])
    candle_index = {time: index for index, time in enumerate(times)}
    cutoff = instant(config["split_at"])
    split = next((i for i, t in enumerate(times) if t >= cutoff), len(times))
    if split == 0 or split == len(times):
        raise ValueError("split must leave candles in both periods")
    experiments = config["experiments"]
    if not isinstance(experiments, list) or not experiments:
        raise ValueError("experiments must be a nonempty list")
    names = set()
    results = []
    for experiment in experiments:
        fields(experiment, {"name", "hypothesis", "desk", "trades"}, "experiment")
        name = experiment["name"]
        if not isinstance(name, str) or not name.strip() or name in names:
            raise ValueError("experiment names must be nonempty and unique")
        names.add(name)
        if not isinstance(experiment["hypothesis"], str) or not experiment["hypothesis"].strip():
            raise ValueError("hypothesis is required")
        if experiment["desk"] not in DESKS:
            raise ValueError("unknown research desk")
        if not isinstance(experiment["trades"], list) or not experiment["trades"]:
            raise ValueError("each experiment requires trades")
        rows = []
        previous_end = -1
        for spec in experiment["trades"]:
            fields(spec, {"entry_at", "plan"}, "trade")
            entry_at = instant(spec["entry_at"])
            if entry_at not in candle_index:
                raise ValueError("entry_at must match a candle timestamp")
            start = candle_index[entry_at]
            if start <= previous_end:
                raise ValueError("trades must be chronological and non-overlapping within each experiment")
            plan = TradePlan(**spec["plan"])
            if plan.symbol != config["symbol"]:
                raise ValueError("plan symbol must match the dataset symbol")
            if plan.entry != candles[start].open:
                raise ValueError("plan entry must equal the selected candle open")
            quantity = position_size(plan)
            if not math.isfinite(quantity) or quantity <= 0:
                raise ValueError("position size must be finite and positive")
            period = "in_sample" if start < split else "out_of_sample"
            end = split if start < split else len(candles)
            outcome = resolve_plan(plan, candles[start:end], ambiguous_policy=config["ambiguous_policy"])
            previous_end = start + outcome.candles_seen - 1
            gross_r = outcome.realized_r
            cost = None if outcome.exit_price is None else costs.round_trip(plan.entry, outcome.exit_price, quantity)
            net_r = None if cost is None else gross_r - cost / (plan.risk_per_share * quantity)
            if net_r is not None and not math.isfinite(net_r):
                raise ValueError("net R calculation overflow")
            rows.append({"entry_at": spec["entry_at"], "period": period, "plan": asdict(plan),
                         "quantity": quantity, **asdict(outcome), "gross_r": gross_r,
                         "round_trip_cost": cost, "net_r": net_r})
        results.append({"name": name, "hypothesis": experiment["hypothesis"], "desk": experiment["desk"],
                        "periods": {p: summary([r for r in rows if r["period"] == p], minimum)
                                    for p in ("in_sample", "out_of_sample")}, "trades": rows})
    engine_hash = engine_fingerprint()
    method = dict(config)
    method.pop("dataset")  # Location does not change the method; bytes do.
    config_hash = digest(canonical(method).encode())
    run_id = digest(canonical({"dataset": data_hash, "config": config_hash, "engine": engine_hash}).encode())
    return {"schema_version": 1, "mode": "paper-research-only", "run_id": run_id,
            "dataset_sha256": data_hash, "config_sha256": config_hash, "engine_sha256": engine_hash,
            "dataset_rows": len(candles), "config": method, "experiments": results}


def markdown(result: dict) -> str:
    def cell(value: object) -> str:
        return str(value).replace("|", "\\|").replace("\n", " ").replace("\r", " ")
    lines = ["TEST_ONLY — software-test output; excluded from trading evidence.", "", "# SC Trading R&D research report", "", "Paper research only. No broker connection or live execution.", "",
             f"Run: `{result['run_id']}`", f"Dataset SHA-256: `{result['dataset_sha256']}`",
             f"Configuration SHA-256: `{result['config_sha256']}`", f"Engine SHA-256: `{result['engine_sha256']}`", "",
             f"Holdout begins: {cell(result['config']['split_at'])}",
             f"Cost assumptions: `{canonical(result['config']['costs'])}`", "",
             "| Experiment | Desk | Period | Submitted | Closed | Open | Ambiguous | Mean net R | Max drawdown R |",
             "|---|---|---|---:|---:|---:|---:|---:|---:|"]
    for e in result["experiments"]:
        for period, stats in e["periods"].items():
            m = stats["net_metrics"]
            mean = f"{m['average_r']:.4f}" if stats["closed"] else "N/A"
            drawdown = f"{m['max_drawdown_r']:.4f}" if stats["closed"] else "N/A"
            lines.append(f"| {cell(e['name'])} | {cell(e['desk'])} | {period} | {stats['submitted']} | {stats['closed']} | {stats['open']} | {stats['ambiguous']} | {mean} | {drawdown} |")
    lines += ["", "## Findings and next experiments", ""]
    for e in result["experiments"]:
        lines.append(f"- {cell(e['name'])}: hypothesis — {cell(e['hypothesis'])}")
        for period, stats in e["periods"].items():
            for warning in stats["warnings"]:
                lines.append(f"  - {period}: {warning}")
        ins, oos = (e["periods"][p] for p in ("in_sample", "out_of_sample"))
        if ins["closed"] and oos["closed"]:
            delta = oos["net_metrics"]["average_r"] - ins["net_metrics"]["average_r"]
            lines.append(f"  - Holdout minus in-sample mean net R: {delta:+.4f}. Descriptive only; no significance claim.")
        lines.append("  - Next: freeze rules before a new untouched period, collect more observations and stress cost assumptions. No automatic promotion.")
    lines += ["", "## Limits", "",
              "Plans are user-supplied and must be frozen before reviewing holdout results. A chronological split does not prove absence of hindsight or selection bias.",
              "In-sample trades cannot consume holdout candles. Positions still open at either period end remain unresolved; no forced liquidation or zero-R imputation.",
              "Entries use candle opens. Costs are deducted from gross P&L after fill resolution; they do not move stop/target trigger prices. Sizing uses gross stop risk, so costs and gaps can exceed the risk budget.",
              "Fractional quantities are assumed. Metrics use net R on initial gross stop risk. Drawdown is a closed-trade R sequence, not marked-to-market portfolio drawdown.",
              "Each experiment is independent. No shared capital, margin, liquidity, partial-fill, scanner or strategy-generation model is implemented.", ""]
    return "\n".join(lines)


def run_batch(config_path: str | Path, output_dir: str | Path) -> Path:
    config_path = Path(config_path)
    result = evaluate(json.loads(config_path.read_text(encoding="utf-8")), config_path.resolve().parent)
    json_text = json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n"
    report = markdown(result)
    destination = Path(output_dir) / result["run_id"]
    destination.mkdir(parents=True, exist_ok=False)  # Preserve previous evidence.
    (destination / "results.json").write_text(json_text, encoding="utf-8")
    (destination / "report.md").write_text(report, encoding="utf-8")
    return destination
