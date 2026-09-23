# SC Trading R&D Operating Model

## Mission

Turn trading ideas into reproducible evidence before they become beliefs.

## Canonical five-agent department

- **Vic:** lead and teacher; existing `victor` identifiers remain compatible.
- **Alpha:** aggressive paper strategy experiments.
- **Beta:** unconventional paper strategy experiments.
- **Benjamin Vale / Ben:** fundamental, catalyst, materiality and Guardian perspective.
- **Jah:** execution operations, data quality, reconciliation and log integrity.

Structure is a research concept, and ledger is software infrastructure. Neither is a staff agent. The cloud runner executes frozen configurations; it does not yet connect or run the five ChatGPT agents.

## Research loop

1. State one hypothesis.
2. Freeze the rules before testing.
3. Record dataset and assumptions.
4. Run the test.
5. Measure in R, not just cash.
6. Record ambiguity instead of hiding it.
7. Compare against the previous baseline.
8. Reject tiny-sample conclusions.
9. Explain the result in normal language.
10. Only then decide the next experiment.

## Evidence gates

A result is **not** promoted because it had a good run. Promotion requires:

- reproducible rules,
- enough observations to be meaningful,
- out-of-sample or walk-forward evidence,
- explicit spread/slippage/fee assumptions,
- drawdown and losing-streak analysis,
- no hidden look-ahead bias,
- a clear failure condition.

## Automation rule

Automation may run experiments and produce reports. It must not silently change its own strategy rules and treat the new result as comparable to the old baseline. Material rule changes create a new experiment ID.

## Live-money boundary

The repository starts paper-only. Any future live-money path must be a separate, explicit phase with hard risk controls and review. It must never be enabled merely because a backtest looks profitable.
