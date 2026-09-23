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

Implemented: declared data provenance/hash/coverage/cadence gates; frozen rolling portfolio selection; hourly/manual paper-only GitHub Actions workflow; unique 14-day report/ledger artifacts; provisional-only synthetic findings; canonical Vic/Alpha/Beta/Ben/Jah department.

Next: verify cloud execution, then define reviewed agent-to-experiment proposals and result handoff to Vic. Add authorized real research datasets, source/calendar checks, preregistered evidence validation and durable archival. External feeds, autonomous ChatGPT handoff, persistent cross-run accounts and live execution remain unimplemented.

## Real-data gateway status

Implemented locally: Twelve Data OHLC adapter, explicit source/identity checks, single-session quality gates, provenance SHA-256, verified cache reuse, protected-holdout Lab and single-instrument portfolio adapters, and TEST_ONLY software-output classification. Authentication passed. A genuine cached dataset plus non-holdout research smoke run is still required before calling this milestone complete.

T212 metadata integration, independently verified broker identity mapping and Practice order placement remain unimplemented. No live order path exists. Staff: Vic / Alpha / Beta / Ben / Jah. Next milestone requires Sonny's review; do not automatically start a Practice broker bridge.
