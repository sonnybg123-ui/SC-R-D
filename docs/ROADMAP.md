# SC Trading R&D Roadmap

## Phase 1 — Foundation

- [x] risk engine
- [x] paper-trade model
- [x] journal
- [x] R-multiple statistics
- [x] drawdown / streak / profit-factor metrics
- [x] five-desk role registry
- [x] deterministic experiment IDs
- [x] OHLC CSV loader
- [x] fixed-plan historical resolver
- [x] explicit same-candle ambiguity policy
- [x] command-line tools
- [x] automated tests
- [x] publish foundation to GitHub

## Phase 2 — Evidence pipeline

- setup tags and market-regime tags
- batch experiment runner
- rolling expectancy by setup
- confidence / sample-size warnings
- Alpha vs Beta stress-test reports
- automatic markdown research reports
- baseline-vs-candidate comparison

## Phase 3 — Market-data research

- add a legal/reliable market-data source
- local caching with dataset fingerprints
- deterministic strategy backtests
- walk-forward / out-of-sample testing
- spread, fee, and slippage models
- look-ahead-bias checks

## Phase 4 — Scheduled R&D

- hourly paper-research job
- reproducible experiment queue
- automatic report artifacts
- compare every candidate with the prior baseline
- no silent strategy self-modification
- failed-test quarantine

## Phase 5 — Only after evidence

Evaluate whether any broker integration is justified. Live execution is not part of the current system and must be a separate reviewed phase.

## Implemented research milestones

- Reproducible frozen-plan batches with cost assumptions and holdout reports.
- Causal rolling-range signals and next-open fills.
- Rolling training-only selection across frozen Victor / Alpha / Beta variants.
- Final holdout withheld by default; explicit revelation recorded in run identity.
- Future-data mutation tests and deterministic output verification.

Stateful paper broker implemented: Decimal cash/position accounting, atomic SQLite ledger replay, cost-inclusive admission and portfolio limits.

Shared-cash replay implemented: fixed-priority causal strategy allocations, synchronized multi-symbol bars, atomic closing valuation, explicit terminal position policy and verified portfolio reports.

Next implementation: research-data provenance/quality gates and frozen walk-forward selection linked to portfolio replay. External market-data downloads, asynchronous feeds and live execution remain unimplemented.
