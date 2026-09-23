# Strategy Lab: deterministic signals and walk-forward research

This is offline, paper-only research. The bundled dataset is a repeated synthetic
price pattern, deliberately small enough for tests. Its results are wiring checks,
not evidence of an edge. No broker, credentials, network market data, live orders,
cash balance, margin or shared-capital portfolio is involved.

## Run

```text
python -m sc_rd lab examples/strategy_lab.json --output reports
```

This writes strict `results.json` and a Markdown report into a full SHA-256 run
directory. Dataset bytes, canonical method, package source and whether the holdout
was revealed determine the identity. Identical runs refuse to overwrite evidence.
Use another output directory to reproduce the same artifacts byte for byte.

The final holdout is excluded from default simulation. When your method and
candidate set are frozen, explicitly reveal it with:

```text
python -m sc_rd lab examples/strategy_lab.json --include-holdout --output reports
```

Once viewed, that sample is consumed. Do not adjust parameters based on it and
call the next result untouched. The switch is a workflow guard, not encryption or
an access-control vault; the local dataset remains readable. Tests exercise the
revelation path on synthetic copies only. Future real holdouts need a documented
research protocol and a fresh dataset after any retuning.

## Signal and fill contract

At completed candle index `t`, inspect only the previous `lookback` candles
`[t-lookback, t)`. A close strictly above their highest high signals long; a close
strictly below their lowest low signals short. Equality is not a breakout. There
is no signal until the full lookback exists. `direction` filters long, short or
both. Current candle highs/lows are not part of the breakout reference window.

The stop is the prior-window low for long or high for short. A signal at `t` can
enter only at open `t+1`; the entry bar's high, low and close never determine entry
price or size. This means the next *available* bar, not a guarantee of continuous
market data. A final-candle signal cannot enter inside that evaluation window.

Stops retain their signal-time price across the opening gap. If the next open is
at or beyond the stop in the adverse direction, skip the entry and record why.
Otherwise calculate stop distance from actual entry, place target at `reward_r`
times that distance, and size fractionally using the configured gross risk budget.
Skip a setup whose target would be nonpositive. No future extreme is consulted.

Existing historical fill rules then apply on the entry bar and later bars:

- An opening gap through an active stop fills at the open, so loss can exceed 1R.
- Opening target fills receive no favorable price improvement.
- If both levels are touched intrabar, use the frozen ambiguity policy.
- `skip` ambiguity leaves exposure unresolved and blocks further entries in that
  window. It is not permission to continue trading as though flat.
- `max_holding_bars` includes the entry bar. If no level is hit, exit at the last
  allowed bar's close only when the complete holding interval fits in the window.
- At an earlier window boundary, leave the trade open and exclude it from closed
  metrics with a warning. Do not force a zero-R outcome or consume the next window.
- One position per candidate at a time. A new signal may be observed at the close
  of an exit bar, but its earliest entry is the following open.

Round-trip costs reuse the explicit fixed-fee, fee-bps, half-spread per side and
adverse-slippage model in [batch research](BATCH_RESEARCH.md). Costs are deducted
after reference-price fills; triggers are not bid/ask-adjusted. Net R uses initial
gross stop risk as denominator. Gaps and costs can exceed the configured budget.

## Rolling evaluation and selection

The last `holdout_bars` are reserved. Development begins with `train_bars`, then
advances by `test_bars`. Before each test, rank candidates using only the preceding
fixed-length training window. A final short test window uses the remaining
development bars, so no development tail is silently dropped.

For each training evaluation, a candidate is eligible only if:

1. At least `minimum_trades` have closed.
2. There are no open or ambiguous training positions.

Rank eligible candidates by mean **net R**. Break exact ties lexically by candidate
name, regardless of configuration ordering. If none qualify, abstain for that test
window. This criterion is descriptive, not a significance test; the selected
candidate may still have a negative mean. No selection authorizes live trading.

Freeze the selected name before evaluating the next test interval. Store all
candidate test results for transparent comparison, alongside the fixed baseline.
Only selected-candidate trades feed the selected walk-forward summary. Abstained
folds are counted, not disguised as zero-return trades. The baseline always runs
for comparison. Do not choose another candidate retrospectively using these test
results and describe it as the originally selected sequence.

Before optional final revelation, rank using the last `train_bars` of development.
Evaluate only that frozen choice plus the configured baseline on the holdout.
If selection abstains, report baseline only and retain the abstention.

Every window starts flat. Earlier candles are available solely for causal signal
warmup; therefore a signal at the immediately preceding close can enter at a
window's first open. Positions do not carry between train/test windows or between
successive test windows. Aggregated R is an independent-window research statistic,
not continuously tradable portfolio equity. Excluded boundary exposure can bias it.

## Configuration

`examples/strategy_lab.json` is the complete schema reference:

- Dataset, symbol, risk budget, cost fields and ambiguity policy follow the batch
  pipeline's local-only contract.
- `train_bars`, `test_bars`, `holdout_bars`, `minimum_trades` are positive integers.
  Every lookback must be shorter than the training window. There must be at least
  one development test bar and a nonempty holdout.
- `baseline` names one of the unique `candidates`.
- Each candidate specifies `name`, desk registry key, positive integer `lookback`,
  positive finite `reward_r`, positive integer `max_holding_bars`, and optional
  `direction` (defaults to `both`). Unknown candidate parameters are rejected.

The example freezes Victor (baseline), Alpha (shorter lookback / larger target R)
and Beta (longer lookback / longer holding limit). These are parameter labels,
not autonomous agents. All versions use the same risk budget and cost assumptions.

## Verified boundaries and remaining work

Regression tests mutate future candles and confirm earlier signals, entry plans,
training rankings and final selection are unchanged. Tests also verify short
symmetry, invalid opening gaps, exit gaps, timeouts, unresolved boundary trades,
candidate ties, abstention, disjoint tests, holdout opt-in, deterministic artifacts
and preservation of prior output. All foundation and batch tests remain in the
full suite.

Walk-forward splits reduce certain forms of future-data leakage; they do not
eliminate researcher hindsight, survivorship bias, data errors, multiple testing
or sensitivity to small samples. Document every candidate and trial. Do not claim
statistical confidence from passing a configurable trade-count threshold.

Next: use reviewed local research data with explicit provenance and adjustment
policy, freeze the experimental protocol, and validate on new unseen periods.
Then implement a stateful paper broker and ledger with cash, positions and
cost-inclusive portfolio risk gates before any scheduling or broker discussion.
