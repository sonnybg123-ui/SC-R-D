# Shared-cash chronological replay

This milestone connects the causal rolling-range Strategy Lab to the persistent
paper broker. Multiple desk allocations inside an experiment share one synthetic
cash balance, collateral pool, exposure/risk limits and drawdown halt. Separate
experiments use independent ledgers with the same initial cash, cost and limit
assumptions. No broker connection, credentials or live orders are involved.

## Run the example

```text
python -m sc_rd portfolio examples/portfolio.json --output reports
```

The example compares a Victor-only portfolio with mixed Alpha/Beta/Victor
allocations. Both synthetic symbols deliberately use the same artificial CSV to
exercise simultaneous signals and competition. These repeated, perfectly
correlated fixtures are software checks, not evidence of a tradable edge.

Each full-hash run directory contains:

- `manifest.json`: running, failed or complete status and input identity.
- `portfolio-NNN.db`: independently audited SQLite ledger for each experiment.
- `results.json`: frozen method, fingerprints, orders/rejections, exits, allocation
  summaries, equity samples and final reconciled broker snapshots.
- `report.md`: portfolio comparison, per-allocation outcomes and limitations.

Existing runs are never overwritten. To reproduce a result, use a different output
directory: JSON, Markdown and ledger heads should match. SQLite file bytes are not
the comparison contract. No filesystem paths are included in research identity.
Dataset bytes, symbol mapping, complete configuration, source code and selected
period determine the run hash.

## Configuration and data

Use `examples/portfolio.json` as the complete schema reference.

- `datasets` maps symbols to local OHLC CSV files relative to the config file.
- All datasets must have the **identical UTC timestamp grid**. Missing or offset
  candles are rejected, never interpolated, forward-filled or silently dropped.
- `initial_cash`, all `costs`, and every `limits` field are explicit assumptions.
  The broker validates positive finite prices, amounts, quantity and capacity.
- `holdout_bars` reserves a positive number of final bars, leaving at least two
  development bars. `minimum_trades` only controls sample-size reporting warnings.
- `end_policy` must be `keep_open` or `liquidate`.
- Experiments have unique names and nonempty `allocations`.
- Every allocation has a unique ASCII `id`, a dataset `symbol`, unique nonnegative
  integer `priority`, positive `risk_budget`, and a frozen Breakout `strategy`.
  Lower priority numbers act first. List order does not override priority.

An allocation can use any registered desk. Two allocations can address the same
symbol, but the broker permits only one open position per symbol across all desks.
Every candidate signal is recorded as filled, broker-rejected or skipped for an
invalid next-open stop/target. A capacity rejection is never silently resized or
assigned to another desk. Priority is a testable research assumption, not an
assertion that a particular desk is better.

## Exact replay order

For each timestamp across the synchronized instruments:

1. Observe all current opens. Determine opening stop gaps or target exits for
   existing positions using only these opens and previously frozen stop/target
   prices. Mark all instruments in one broker event, then settle opening exits.
   A target position is marked at its capped target fill, avoiding fictional gains
   at a better open that the fill model does not award. Opening losses can latch
   the drawdown halt before any new risk is considered.
2. Generate each allocation's signal from the preceding completed candle and
   earlier lookback only. Warmup can use earlier data outside the selected period.
   Fill eligible signals at the current open, in ascending fixed priority, through
   ordinary broker admission. Entries never inspect current highs/lows/closes.
3. Finish **all** admissions before consuming the current candle's ranges. Thus an
   intrabar winner cannot fund another signal at that same candle's open. Cash
   released by a known opening exit can fund an entry, since that exit occurs first.
4. Process all symbols' full OHLC bars in one atomic `process_bars` event. Stops
   win intrabar ambiguity. Apply final closing marks and evaluate portfolio equity
   together, preventing symbol order from creating a false intermediate halt.
5. Close surviving positions whose inclusive maximum holding-bar count expires,
   using that bar's close. On the final selected bar, apply the configured end
   policy. Record open, post-entry and closing equity samples for the timestamp.

The candle timestamp labels the bar; phase order supplies within-bar causality.
The actual intrabar path and intrabar portfolio drawdown remain unknown. No
position opens on a final-close signal because no next open lies in the period;
such signals are listed separately. Signals generated while a position is open
may reach admission and receive an explicit occupied-symbol rejection. Maximum
holding time belongs to the allocation that actually opened the position.

## End policy and final holdout

`keep_open` retains remaining positions in the ledger at their final mark. They
contribute to equity and unresolved-position warnings but not closed-trade means.
`liquidate` explicitly exits them at the last selected close and charges exit
costs. These exits are labelled `replay-end`; ordinary timeouts are
`replay-timeout`. The broker also records dedicated opening-gap/target reasons.

Default development replay stops before the reserved final bars. It cannot carry
positions or read exit candles across that boundary. An explicit final evaluation:

```text
python -m sc_rd portfolio examples/portfolio.json --period holdout --output reports
```

starts with fresh synthetic cash and no positions, using development bars only as
causal signal warmup. The result is marked **consumed-do-not-retune**. Freeze the
entire allocation set, priorities, costs and limits before viewing it. Repeating
or retuning does not create another untouched sample. The coordinator does not
automatically import walk-forward winners or select a best portfolio after seeing
the final outcomes. Hashing and validating the complete dataset does not feed
holdout values into development decisions.

## Persistence, accounting and limits

Every broker event remains atomic and replay-verifiable. Multi-symbol bar batches
validate duplicate timestamps before applying any symbol and evaluate the final
combined state once. Existing single-bar commands and old ledger results retain
their prior behavior. Corrupt or incompatible ledgers fail closed.

A run uses dedicated new ledgers. Do not concurrently issue manual commands into
them. The coordinator verifies that its owned positions match the ledger at the
end and reopens every ledger for a full audit. The whole multi-experiment run is
not one database transaction: an interruption may leave valid partial ledgers and
a `running` or `failed` manifest. Only `complete` denotes a finished run. There is
no automatic resume or overwrite; rerun in a new output directory for recovery.

Cash costs, six-decimal quantity steps, cost-inclusive reserved risk, conservative
short collateral and permanent drawdown halts follow [paper broker](PAPER_BROKER.md).
Mark-based equity is distinct from cash. Closed-trade net R is distinct from
portfolio equity returns; open positions are not zero-return closed trades.
Reported maximum drawdown is sampled across replay phases, not continuously
observed market drawdown. Gaps and costs can exceed the requested loss budget.

The full-replay ledger favors auditability over throughput. This implementation is
for bounded local research datasets; it is not a high-frequency execution engine.
It assumes one currency, synchronized bars and full fills. It has no asynchronous
feed joining, FX conversion, liquidity/partial-fill model, borrow availability,
corporate actions, market-data download or broker authentication.

## Next milestone

Add an explicit research-data manifest and quality gates (provenance, timeframe,
adjustment policy and coverage), then connect frozen walk-forward selection to
portfolio replay without using the final holdout for tuning. Keep test results,
all candidate trials and unresolved exposure visible before considering scheduling.
