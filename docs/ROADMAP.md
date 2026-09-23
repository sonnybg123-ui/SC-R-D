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
- [ ] publish foundation to GitHub

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
