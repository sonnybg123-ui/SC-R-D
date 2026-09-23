"""Rolling training-only strategy selection and opt-in final holdout."""
from __future__ import annotations

import json
import math
from pathlib import Path

from .research import Costs, canonical, digest, engine_fingerprint, fields, read_dataset, summary
from .strategy import Breakout, simulate


def select(training: list[dict], minimum: int) -> str | None:
    """Rank eligible training means; break exact ties lexically by frozen name."""
    eligible = [r for r in training if r["summary"]["closed"] >= minimum
                and r["summary"]["open"] == 0 and r["summary"]["ambiguous"] == 0]
    if not eligible:
        return None
    winner = min(eligible, key=lambda r: (-r["summary"]["net_metrics"]["average_r"], r["strategy"]["name"]))
    return winner["strategy"]["name"]


def evaluate_lab(config: dict, base_dir: Path, *, include_holdout: bool = False) -> dict:
    config = json.loads(canonical(config))
    fields(config, {"schema_version", "dataset", "symbol", "risk_budget", "costs", "ambiguous_policy",
                    "minimum_trades", "train_bars", "test_bars", "holdout_bars", "baseline", "candidates"}, "strategy lab")
    if type(config["schema_version"]) is not int or config["schema_version"] != 1:
        raise ValueError("unsupported schema_version")
    for key in ("minimum_trades", "train_bars", "test_bars", "holdout_bars"):
        if type(config[key]) is not int or config[key] < 1:
            raise ValueError(f"{key} must be a positive integer")
    if not isinstance(config["symbol"], str) or not config["symbol"].strip():
        raise ValueError("symbol is required")
    risk = config["risk_budget"]
    if isinstance(risk, bool) or not isinstance(risk, (int, float)) or not math.isfinite(risk) or risk <= 0:
        raise ValueError("risk_budget must be finite and positive")
    fields(config["costs"], {"fee_per_side", "fee_bps", "spread_bps", "slippage_bps"}, "costs")
    costs = Costs(**config["costs"])
    if config["ambiguous_policy"] not in {"conservative", "optimistic", "skip"}:
        raise ValueError("unsupported ambiguous_policy")
    if not isinstance(config["candidates"], list) or not config["candidates"]:
        raise ValueError("nonempty candidate list required")
    strategies = [Breakout(**c) for c in config["candidates"]]
    names = [s.name for s in strategies]
    if len(set(names)) != len(names) or config["baseline"] not in names:
        raise ValueError("candidate names must be unique and baseline must name a candidate")
    strategies.sort(key=lambda s: s.name)
    candles, _, dataset_hash = read_dataset(base_dir / config["dataset"])
    development_end = len(candles) - config["holdout_bars"]
    if development_end <= config["train_bars"]:
        raise ValueError("dataset must allow training, development testing and final holdout")
    if max(s.lookback for s in strategies) >= config["train_bars"]:
        raise ValueError("train_bars must exceed every lookback")

    def run(start: int, end: int, candidates: list[Breakout]) -> list[dict]:
        return [simulate(candles, s, start, end, symbol=config["symbol"], risk_budget=risk,
                         costs=costs, ambiguous_policy=config["ambiguous_policy"],
                         minimum_trades=config["minimum_trades"]) for s in candidates]

    folds = []
    selected_rows = []
    baseline_rows = []
    start = config["train_bars"]
    while start < development_end:
        end = min(start + config["test_bars"], development_end)
        training = run(start - config["train_bars"], start, strategies)
        chosen = select(training, config["minimum_trades"])
        # Selection is fixed before any test outcomes are calculated.
        testing = run(start, end, strategies)
        for evaluation in testing:
            if evaluation["strategy"]["name"] == chosen:
                selected_rows.extend(evaluation["trades"])
            if evaluation["strategy"]["name"] == config["baseline"]:
                baseline_rows.extend(evaluation["trades"])
        folds.append({"number": len(folds) + 1, "train_start": start - config["train_bars"],
                      "test_start": start, "test_end_exclusive": end,
                      "selected": chosen, "training": training, "testing": testing})
        start = end
    final_training = run(development_end - config["train_bars"], development_end, strategies)
    final_choice = select(final_training, config["minimum_trades"])
    final_holdout = None
    if include_holdout:
        permitted = {config["baseline"], final_choice}
        final_holdout = run(development_end, len(candles), [s for s in strategies if s.name in permitted])
    method = dict(config)
    method.pop("dataset")
    engine_hash = engine_fingerprint()
    config_hash = digest(canonical(method).encode())
    identity = {"kind": "strategy-lab-v1", "dataset": dataset_hash, "config": config_hash,
                "engine": engine_hash, "include_holdout": include_holdout}
    return {"mode": "paper-research-only", "schema_version": 1, "run_id": digest(canonical(identity).encode()),
            "dataset_sha256": dataset_hash, "config_sha256": config_hash, "engine_sha256": engine_hash,
            "config": method, "dataset_rows": len(candles), "holdout_start": development_end,
            "holdout_status": "revealed-do-not-retune-on-this-period" if include_holdout else "withheld",
            "folds": folds, "walk_forward_selected": summary(selected_rows, config["minimum_trades"]),
            "walk_forward_baseline": summary(baseline_rows, config["minimum_trades"]),
            "abstained_folds": sum(f["selected"] is None for f in folds),
            "final_training": final_training, "final_selected": final_choice, "final_holdout": final_holdout}


def lab_markdown(result: dict) -> str:
    def clean(value: object) -> str:
        return str(value).replace("|", "\\|").replace("\n", " ").replace("\r", " ")

    def line(label: str, s: dict) -> str:
        mean = f"{s['net_metrics']['average_r']:.4f}" if s["closed"] else "N/A"
        return f"| {clean(label)} | {s['submitted']} | {s['closed']} | {s['open']} | {s['ambiguous']} | {mean} |"

    lines = ["# SC Trading R&D Strategy Lab", "", "Paper research only; no broker or live execution.",
             "Bundled synthetic fixtures are wiring checks, not evidence of a market edge.", "",
             f"Run: `{result['run_id']}`", f"Dataset SHA-256: `{result['dataset_sha256']}`",
             f"Method SHA-256: `{result['config_sha256']}`", f"Engine SHA-256: `{result['engine_sha256']}`", "",
             f"Final holdout: **{result['holdout_status']}** (starts at bar {result['holdout_start']}).",
             f"Frozen final selection: {clean(result['final_selected']) if result['final_selected'] else 'abstain: no eligible candidate'}.",
             f"Costs: `{canonical(result['config']['costs'])}`", "",
             "## Walk-forward comparison", "", "| Sequence | Submitted | Closed | Open | Ambiguous | Mean net R |",
             "|---|---:|---:|---:|---:|---:|",
             line("Training-selected candidates", result["walk_forward_selected"]),
             line("Fixed baseline", result["walk_forward_baseline"]), "",
             f"Abstained folds: {result['abstained_folds']}. Minimum training closed trades: {result['config']['minimum_trades']}.", "",
             "## Frozen candidate comparisons", "",
             "| Fold / candidate / role | Submitted | Closed | Open | Ambiguous | Mean net R |",
             "|---|---:|---:|---:|---:|---:|"]
    for fold in result["folds"]:
        for evaluation in fold["testing"]:
            name = evaluation["strategy"]["name"]
            role = "selected" if name == fold["selected"] else "comparison"
            lines.append(line(f"{fold['number']} / {name} / {role}", evaluation["summary"]))
    if result["final_holdout"] is not None:
        lines += ["", "## Final holdout (now consumed)", "",
                  "| Candidate | Submitted | Closed | Open | Ambiguous | Mean net R |", "|---|---:|---:|---:|---:|---:|"]
        for evaluation in result["final_holdout"]:
            lines.append(line(evaluation["strategy"]["name"], evaluation["summary"]))
    lines += ["", "## Evidence warnings", ""]
    groups = [("Selected sequence", result["walk_forward_selected"]), ("Baseline", result["walk_forward_baseline"])]
    for fold in result["folds"]:
        for period in ("training", "testing"):
            groups.extend((f"Fold {fold['number']} {period} {e['strategy']['name']}", e["summary"]) for e in fold[period])
    groups.extend((f"Final training {e['strategy']['name']}", e["summary"]) for e in result["final_training"])
    groups.extend((f"Holdout {e['strategy']['name']}", e["summary"]) for e in (result["final_holdout"] or []))
    for label, stats in groups:
        for warning in stats["warnings"]:
            lines.append(f"- {clean(label)}: {warning}")
    lines += ["", "## Interpretation and next experiment", "",
              "Signals use a completed close versus strictly preceding highs/lows. Entry is the next available candle open. Missing bars are not synthesized.",
              "Training selection maximizes mean net R among candidates with enough closed trades and no unresolved training exposure; exact ties use lexical name order. No eligible candidate means abstain. A highest-ranked candidate can still lose money.",
              "Each window starts flat; historical candles provide signal warmup only. Open boundary positions remain unresolved and do not carry into the next window. This is independent research-window evaluation, not a continuous portfolio simulation.",
              "Same-candle ambiguity follows the configured policy. With skip, further entries stop for that window because exposure is uncertain. Maximum holding time closes at the last permitted bar close only if the full holding period fits.",
              "Costs are deducted after reference-price fills. Stops retain their signal-time price; targets and fractional sizing use the actual next-open distance. Gaps and costs can exceed the gross risk budget.",
              "Closed-trade R drawdown is not mark-to-market portfolio drawdown. Small samples and excluded boundary trades can bias comparison. No statistical significance or profitability claim is made.",
              "Keep the final holdout hidden while developing. Explicit revelation consumes it; rerunning or retuning does not create a new untouched sample. This is a workflow guard, not an access-control vault.",
              "Next: freeze the full candidate set and method, evaluate on new research data, then add stateful paper cash/position accounting and cost-inclusive portfolio limits. Never auto-promote to live execution.", ""]
    return "\n".join(lines)


def run_lab(config_path: str | Path, output_dir: str | Path, *, include_holdout: bool = False) -> Path:
    path = Path(config_path)
    result = evaluate_lab(json.loads(path.read_text(encoding="utf-8")), path.resolve().parent, include_holdout=include_holdout)
    payload = json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n"
    report = lab_markdown(result)
    destination = Path(output_dir) / result["run_id"]
    destination.mkdir(parents=True, exist_ok=False)
    (destination / "results.json").write_text(payload, encoding="utf-8")
    (destination / "report.md").write_text(report, encoding="utf-8")
    return destination
