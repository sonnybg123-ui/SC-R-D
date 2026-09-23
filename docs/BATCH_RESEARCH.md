# Batch research pipeline

This milestone evaluates frozen, user-supplied plans against local OHLC data.
It is an offline paper-research tool, with no broker credentials, network feeds,
order submission, automatic strategy tuning or promotion to live trading.

## Run the synthetic example

From the repository root, after installing `.[dev]`:

```text
python -m sc_rd batch examples/batch.json --output reports
```

The example has four artificial candles and Victor, Alpha and Beta experiments.
It demonstrates wiring and failure cases, not a profitable strategy or market
evidence. Beta demonstrates positions unresolved at each period boundary.

Output is `reports/<full SHA-256 run ID>/results.json` and `report.md`. Reports
are ignored by Git. An identical run refuses to overwrite that directory. To
reproduce it, choose another output directory and compare the files byte for
byte. Keep the original input CSV and config locally with your research evidence.

## Input contract

Use `examples/batch.json` as the complete schema example. Unknown top-level,
experiment, trade-wrapper and cost fields are rejected to catch misspellings.

- `schema_version`: integer `1`.
- `dataset`: local CSV path relative to the configuration file.
- `symbol`: declared instrument for the CSV; every plan must match it.
- `split_at`: timezone-aware ISO timestamp. Candles before it are in-sample;
  candles at or after it are out-of-sample. Both partitions need candles.
- `costs`: explicitly supply all four nonnegative cost assumptions below.
- `ambiguous_policy`: `conservative`, `optimistic`, or `skip`.
- `minimum_trades`: positive closed-trade reporting threshold, not a confidence
  level or statistical significance test.
- `experiments`: uniquely named experiments, each with a hypothesis, a desk key
  (`victor`, `alpha`, `beta`, `structure`, `ledger`) and a nonempty trade list.
- Each trade has `entry_at` and a `plan` matching the existing TradePlan model.
  Entry must match a dataset timestamp and the candle's open exactly.

CSV columns must be exactly `timestamp,open,high,low,close` (order may vary).
Timestamps must be timezone-aware, unique and strictly ascending after conversion
to UTC. The loader never sorts bad input silently. Prices must be finite,
positive and have valid OHLC ranges. Use one instrument and one currency.
Feed adjustment policy and data quality remain the researcher's responsibility.

Trades must be chronological and non-overlapping within each experiment.
Experiments are independent; they do not consume shared capital. Fractional
quantities are used. A trade resolves only against candles within its entry
partition, including the entry candle. No in-sample position can consume holdout
data. A position still open at the boundary remains open; it is not carried,
force-closed, counted as breakeven or assigned a zero result.

## Costs and R

All currency amounts use the OHLC price currency. One basis point is 0.0001.
With quantity `q`, reference entry `e`, resolved exit `x` and initial stop `s`:

```text
q = risk_budget / abs(e - s)
initial_gross_risk = abs(e - s) * q
round_trip_cost = 2 * fee_per_side
                + (e + x) * q
                  * (fee_bps + spread_bps / 2 + slippage_bps) / 10000
net_R = gross_R - round_trip_cost / initial_gross_risk
```

`fee_per_side` is a fixed fee on each side. `fee_bps` applies to notional on each
side. `spread_bps` is the full quoted spread, so half is deducted on each side.
`slippage_bps` is adverse slippage on each side. Costs are deducted from realized
P&L after resolving reference-price triggers; they do not alter stop/target
touches. This is a simplified cost model, not a bid/ask fill simulator.

Sizing uses gross stop risk, not a cost-inclusive loss cap. Costs and gaps can
therefore produce losses greater than the requested risk budget or -1R.
There is no currency conversion, borrow interest, liquidity, partial fill or
margin model. Open/ambiguous trades have no round-trip cost or net R until closed.

## Evidence and reproducibility

Run identity includes:

1. SHA-256 of the exact CSV bytes parsed from a single read.
2. SHA-256 of canonical configuration, excluding only the dataset filesystem
   location. Changed costs, rules, split, hypotheses or desk assignment change it.
3. SHA-256 of a sorted manifest of all package Python source files.

The strict JSON result includes the frozen method, each evaluated trade, costs,
gross and net R, period summaries and all three hashes. Infinite profit factor
is encoded as the string `infinite`, never a nonstandard JSON numeric value.
Runtime-generated dates are excluded so identical inputs produce identical
artifacts in the same engine environment.

The report separates in-sample and holdout net-R metrics. Open and ambiguous
counts remain visible. Closed-trade means can be biased when outcomes are
unresolved; both this and small samples generate warnings. Drawdown is the
cumulative closed-trade R sequence, not portfolio equity or mark-to-market risk.
Differences between period means are descriptive, not significance tests.

You must freeze entry rules and parameters before inspecting the holdout.
Supplying retrospective plans can introduce hindsight. Hashes identify inputs;
they do not prove when a hypothesis was written. The pipeline prevents cross-split
candle consumption but does not establish absence of selection bias. There is
no fitted strategy, walk-forward training or automatic winner selection yet.

## Next milestone

Add deterministic signal generation using only candles available at each decision
time, then test it with next-bar fills, walk-forward windows and a fresh untouched
holdout. Preserve a baseline and report all candidate trials to limit selection
bias. Add a cost-inclusive portfolio risk gate before a stateful paper broker.
