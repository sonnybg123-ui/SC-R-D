"""Data-gated rolling selection of frozen paper portfolios, with a sealed holdout by default."""
from __future__ import annotations

import json
from decimal import Decimal, localcontext
from pathlib import Path

from .data_quality import validate_manifest
from .portfolio import prepare, replay_experiment
from .research import canonical, digest, fields


def choose(training: list[dict], minimum: int) -> str | None:
    eligible = [t for t in training if t["final"]["reconciled"] and not t["final"]["state"]["positions"]
                and not t["final"]["state"]["halted"] and len(t["final"]["state"]["closed"]) >= minimum]
    if not eligible:
        return None
    # All candidate portfolios use the same initial cash and fees/limits.
    return min(eligible, key=lambda t: (-Decimal(t["final"]["balances"]["realized_net_pnl"]), t["name"]))["name"]


def load_inputs(path: Path) -> tuple:
    config = json.loads(path.read_text(encoding="utf-8"))
    fields(config, {"schema_version", "portfolio", "data_manifest", "baseline", "train_bars",
                    "test_bars", "minimum_training_trades"}, "walk-forward config")
    if type(config["schema_version"]) is not int or config["schema_version"] != 1:
        raise ValueError("unsupported walk-forward schema_version")
    for key in ("train_bars", "test_bars", "minimum_training_trades"):
        if type(config[key]) is not int or config[key] < 1:
            raise ValueError(f"{key} must be a positive integer")
    portfolio_path = path.resolve().parent / config["portfolio"]
    manifest_path = path.resolve().parent / config["data_manifest"]
    portfolio = json.loads(portfolio_path.read_text(encoding="utf-8"))
    prepared = prepare(portfolio, portfolio_path.resolve().parent, "development")
    portfolio, data, grid, _, cutoff, method, identity = prepared
    quality = validate_manifest(json.loads(manifest_path.read_text(encoding="utf-8")), data, grid, identity["datasets"])
    if config["baseline"] not in {e["name"] for e in portfolio["experiments"]}:
        raise ValueError("baseline must name a frozen portfolio experiment")
    if config["train_bars"] >= cutoff:
        raise ValueError("training must leave at least one development test bar")
    if max(a["strategy"]["lookback"] for e in portfolio["experiments"] for a in e["allocations"]) >= config["train_bars"]:
        raise ValueError("training window must exceed every strategy lookback")
    return config, portfolio, data, grid, cutoff, method, identity, quality


def markdown(result: dict) -> str:
    def clean(value):
        return str(value).replace("|", "\\|").replace("\n", " ").replace("\r", " ")
    lines = ["TEST_ONLY — software-test output; excluded from trading evidence.", "", "# SC Trading R&D walk-forward portfolios", "", "Offline paper research only. Synthetic fixtures are not evidence of an investment edge.", "",
             f"Run: `{result['run_id']}`", f"Data manifest: `{result['data_quality']['manifest_sha256']}`",
             f"Engine: `{result['identity']['engine']}`", f"Final holdout: **{result['holdout_status']}**.",
             f"Frozen final choice: {clean(result['final_selected']) if result['final_selected'] else 'abstain'}.", "",
             "| Fold | Training bars | Test bars | Frozen choice | Selected net P&L | Baseline net P&L |",
             "|---|---|---|---|---:|---:|"]
    for fold in result["folds"]:
        lines.append(f"| {fold['number']} | [{fold['train_start']}, {fold['test_start']}) | [{fold['test_start']}, {fold['test_end_exclusive']}) | {clean(fold['selected']) if fold['selected'] else 'abstain'} | {fold['selected_net_pnl']} | {fold['baseline_net_pnl']} |")
    lines += ["", f"Selected fixed-capital window P&L sum: {result['selected_net_pnl_sum']}.",
              f"Baseline fixed-capital window P&L sum: {result['baseline_net_pnl_sum']}.",
              f"Abstained folds: {result['abstained_folds']}.", "",
              "These sums describe independent equal-starting-cash windows, not a compounded continuous account. Open positions are excluded from realized P&L, never silently treated as closed zero-return trades.", "",
              "## Data checks", ""]
    for symbol, item in result["data_quality"]["datasets"].items():
        lines.append(f"- {clean(symbol)}: {item['rows']} rows, SHA-256 `{item['actual_sha256']}`, {item['first_open']} to {item['last_open']}.")
        lines.extend(f"  - {clean(w)}" for w in item["warnings"])
    lines += ["", "## Portfolio outcomes and evidence warnings", ""]
    groups = []
    for fold in result["folds"]:
        for phase in ("training", "testing"):
            groups.extend((f"Fold {fold['number']} {phase}", t) for t in fold[phase])
    groups.extend(("Final training", t) for t in result["final_training"])
    groups.extend(("Final holdout", t) for t in (result["final_holdout"] or []))
    for label, trial in groups:
        state = trial["final"]["state"]
        lines.append(f"- {clean(label)} / {clean(trial['name'])}: {len(state['closed'])} closed, {len(state['positions'])} open; net P&L {trial['final']['balances']['realized_net_pnl']}; halted={state['halted']}; ledger `{trial['ledger_file']}`.")
        for allocation in trial["attribution"]:
            lines.extend(f"  - {clean(allocation['allocation_id'])}: {w}" for w in allocation["summary"]["warnings"])
    lines += ["", "## Interpretation", "",
              "Candidates are ranked by training realized net P&L after costs, using equal initial cash and portfolio limits. Eligibility requires the minimum closed-trade count, no open positions, no drawdown halt, and a reconciled ledger. Exact ties use lexical experiment name; no eligible candidate means abstain. The best eligible candidate can still lose money.",
              "The choice is frozen before test simulation. Test evaluation includes only that choice and the predeclared baseline. Training and test windows start flat with reset synthetic cash; prior bars provide causal signal warmup only. The complete allocation/priority set remains frozen.",
              "Final training ends before the reserved holdout. Its choice is saved before any optional holdout evaluation. Once explicitly revealed, that sample is consumed and cannot justify retuning and claiming a fresh test.",
              "Provenance is declared metadata; these checks do not verify vendor claims, licensing rights, survivorship bias, adjusted-price truth or statistical significance. No cloud service or broker connection is enabled by this report.", ""]
    return "\n".join(lines)


def run_walkforward(config_path: str | Path, output_dir: str | Path, *, include_holdout: bool = False) -> Path:
    config, portfolio, data, grid, cutoff, method, source_identity, quality = load_inputs(Path(config_path))
    settings = {k: v for k, v in config.items() if k not in {"portfolio", "data_manifest"}}
    identity = {"kind": "portfolio-walkforward-v1", "portfolio": source_identity,
                "engine": source_identity["engine"], "quality": quality["manifest_sha256"],
                "settings": settings, "include_holdout": include_holdout}
    run_id = digest(canonical(identity).encode())
    destination = Path(output_dir) / run_id
    destination.mkdir(parents=True, exist_ok=False)
    manifest = {"status": "running", "run_id": run_id, "identity": identity}
    def write_manifest():
        (destination / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_manifest()
    experiments = sorted(portfolio["experiments"], key=lambda e: e["name"])
    def run(start, end, candidates, label):
        return [replay_experiment(portfolio, e, data, grid, start, end, destination / f"{label}-{i:03d}.db")
                for i, e in enumerate(candidates)]
    try:
        folds = []
        start = config["train_bars"]
        while start < cutoff:
            end = min(start + config["test_bars"], cutoff)
            training = run(start-config["train_bars"], start, experiments, f"fold-{len(folds):03d}-train")
            selected = choose(training, config["minimum_training_trades"])
            # Do not move selection below the test evaluation.
            testing = run(start, end, [e for e in experiments if e["name"] in {selected, config["baseline"]}], f"fold-{len(folds):03d}-test")
            pnls = {t["name"]: t["final"]["balances"]["realized_net_pnl"] for t in testing}
            folds.append({"number": len(folds)+1, "train_start": start-config["train_bars"],
                          "test_start": start, "test_end_exclusive": end, "selected": selected,
                          "training": training, "testing": testing,
                          "selected_net_pnl": pnls.get(selected, "0"), "baseline_net_pnl": pnls[config["baseline"]]})
            start = end
        final_training = run(cutoff-config["train_bars"], cutoff, experiments, "final-train")
        final_selected = choose(final_training, config["minimum_training_trades"])
        final_holdout = None
        if include_holdout:
            final_holdout = run(cutoff, len(grid), [e for e in experiments if e["name"] in {final_selected, config["baseline"]}], "holdout")
        with localcontext() as context:
            context.prec = 40
            selected_sum = str(sum((Decimal(f["selected_net_pnl"]) for f in folds), Decimal(0)))
            baseline_sum = str(sum((Decimal(f["baseline_net_pnl"]) for f in folds), Decimal(0)))
        result = {"data_classification": "SYNTHETIC", "evidence_status": "TEST_ONLY", "evidence_eligible": False, "mode": "paper-research-only", "run_id": run_id, "identity": identity, "method": method,
                  "settings": settings, "data_quality": quality, "folds": folds, "final_training": final_training,
                  "final_selected": final_selected, "final_holdout": final_holdout,
                  "holdout_status": "consumed-do-not-retune" if include_holdout else "withheld",
                  "selected_net_pnl_sum": selected_sum, "baseline_net_pnl_sum": baseline_sum,
                  "abstained_folds": sum(f["selected"] is None for f in folds)}
        (destination / "results.json").write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
        (destination / "report.md").write_text(markdown(result), encoding="utf-8")
        manifest["status"] = "complete"
        write_manifest()
    except Exception:
        manifest["status"] = "failed"
        try:
            write_manifest()
        except OSError:
            pass
        raise
    return destination
