# Offline paper broker and persistent ledger

This module records **synthetic paper positions only**. It has no network client,
broker adapter, credentials, live order routing or access to actual accounts.
Starting cash is an arbitrary research assumption, not an account balance.

## Try the complete synthetic lifecycle

```text
python -m sc_rd paper demo data/local/paper-demo.db
python -m sc_rd paper status data/local/paper-demo.db
python -m sc_rd paper audit data/local/paper-demo.db
```

The demo initializes synthetic cash, opens a long and a collateralized short on
different synthetic symbols, rejects a third position, marks both, processes their
target exits and reloads the ledger to verify it. It creates seven events and never
overwrites a database. Use a fresh filename if the example already exists.

`status` includes cash/equity, positions, closed trades, net-R metrics and risk
flags. `audit` verifies every event and returns balances, event count and ledger
head without the full position history. Currency values are JSON decimal strings;
summary R metrics use floats and encode infinite profit factor as `infinite`.

## Individual commands

Initialize with the example cost and limit configuration:

```text
python -m sc_rd paper init data/local/research.db --cash 10000 --config examples/paper_config.json --at 2026-01-01T09:00:00Z
python -m sc_rd paper open data/local/research.db examples/paper_plan.json --id entry-001 --at 2026-01-01T09:00:00Z --desk victor
python -m sc_rd paper close data/local/research.db entry-001 --price 110 --id exit-001 --at 2026-01-01T09:15:00Z
```

Additional commands:

```text
python -m sc_rd paper mark DATABASE PRICES_JSON --id UNIQUE_ID --at ISO_TIMESTAMP
python -m sc_rd paper bar DATABASE SYMBOL CANDLE_JSON --id UNIQUE_ID
```

`PRICES_JSON` is a mapping such as `{"SYNTH": 102}`. `CANDLE_JSON` has `timestamp`,
`open`, `high`, `low`, `close`, matching the existing Candle model. These files are
local research inputs; private datasets and generated journals belong in ignored
directories. Do not put credentials or personal financial data into any field.

`open` optionally accepts `--quantity`; otherwise it computes a quantity within
the plan's risk budget and the configured per-trade cap. Explicit quantities must
be positive multiples of 0.000001 and pass the same gates. One position per symbol
is supported: no pyramiding, hedging the same symbol, partial fills or partial exits.

Each mutation needs a unique command ID and a timezone-aware research timestamp.
The opening command ID becomes the position ID. Repeating the exact same command
ID/payload returns its original result, even after restart or later events. Reusing
the ID for different content fails. A previously rejected request stays rejected
on identical retry; use a new ID for a new decision. Rejected CLI orders exit with
status 2 and print their recorded reason.

Events cannot move backwards in research time. Equal timestamps are allowed for
ordered operations on multiple symbols. A processed candle cannot be processed
again under a new ID, and a new position cannot be inserted at or before a candle
already processed for that symbol. A caller should submit next-open entries before
the matching bar event; never supply a signal derived from that bar's future close.

## Cost-inclusive sizing and limits

Costs reuse the research model: fixed fee per side plus notional fee basis points,
half quoted spread per side, and adverse slippage basis points. They are deducted
as cash expenses without moving the reference entry, stop or target prices.

For entry `e`, stop `s`, fixed fee per side `f`, combined per-side rate `k`, and
budget `b = min(plan risk budget, max_trade_risk)`:

```text
quantity = floor_to_0.000001((b - 2*f) / (abs(e-s) + (e+s)*k))
reserved_risk = abs(e-s)*quantity + cost(e,quantity) + cost(s,quantity)
```

If costs consume the budget or the resulting quantity is zero, reject the trade.
Explicit quantities are never silently clipped. Every admission checks:

- Initial stop loss including entry/stop-exit costs is within the per-trade cap.
- Sum of reserved risks is within `max_total_risk`.
- Marked gross long-plus-short exposure is within `max_gross_exposure`.
- Position count is within `max_positions`.
- Available cash remains nonnegative after collateral and estimated exit costs.
- Marks for existing positions are no older than `max_mark_age_seconds`, measured
  against this event's research timestamp, not wall-clock time.
- No latched drawdown/insolvency halt; entry costs cannot trigger one either.

The plan's actual supplied entry is used for sizing. Automated Strategy Lab
integration must construct that plan at the next available open. This broker API
does not itself scan, schedule orders or fetch prices.

Limits and costs are frozen when the database is created. To change assumptions,
start another paper ledger. There is deliberately no deposit, reset-halt or
edit-history command that could conceal a research failure.

## Cash, collateral and equity

All prices and cash use one synthetic currency with Decimal arithmetic (40-digit
internal precision). There is no FX conversion or automatic cent rounding.

- Long entry subtracts entry notional and entry cost from cash. Closing adds exit
  notional less exit cost.
- Short entry adds sale proceeds less entry cost to cash, but reserves **twice
  current short market value** as collateral (cover liability plus matching equity
  backing). Sale proceeds are not freely reusable capital. Closing subtracts cover
  notional and exit cost, releasing the position's collateral.
- Estimated exit costs at current marks are additionally reserved for all open
  positions when calculating available cash. They become actual expenses only
  when a position exits.
- Equity is cash plus marked long assets minus short liabilities. Mark updates
  change equity and collateral, never cash.

Every event and reload reconciles:

```text
cash = sum(all recorded cash deltas, including synthetic initialization)
equity = initial cash + closed net P&L + open gross P&L - open entry costs
```

Reserved stop risk stays fixed at entry; it is not released just because a mark
improves. Net R divides realized P&L after both costs by **initial gross stop risk**,
matching the research pipeline. Thus an ordinary stopped trade with costs can be
below -1R even while its cash loss stays within its cost-inclusive budget.

The short collateral rule is a conservative research assumption, not a real
broker's margin schedule. Borrow availability, interest, dividends, corporate
actions and financing costs are not simulated.

## Exits, drawdown and breaches

`bar` applies conservative stop/target rules: an opening stop gap fills at the open;
an opening target fills at target without favorable improvement; a stop and target
both touched intrabar resolve to the stop with an explicit ambiguity reason.
Any remaining position marks to the bar close. `mark` only values positions; it
does not imply a stop/target fill. Manual paper exits are explicit `close` commands.

Drawdown is measured from the highest sampled marked equity. Reaching
`max_drawdown`, or nonpositive equity, permanently halts new entries in that ledger.
Exits and valuation remain available. Marks can also reveal exposure/collateral
breaches; status reports these rather than hiding them. There is no automatic
liquidation or intrabar equity-path inference. Batch marks update several symbols
atomically; separate same-time symbol events follow their supplied order.

Gaps can exceed reserved risk, exhaust collateral and produce negative synthetic
cash. Exits still execute and record the loss. These controls constrain admission;
they do not guarantee a hard loss cap or protect real money.

## Persistence and verification

SQLite transactions use `BEGIN IMMEDIATE` to serialize admissions and prevent two
concurrent commands from spending the same capacity. Events, results and complete
state snapshots are stored together with full synchronous durability. A failed
insert rolls back the complete command. Initialization refuses existing paths;
an interrupted initialization may leave an unusable new file and will fail closed.

The ledger is append-only through this API and database update/delete triggers.
Each event includes a sequence and chained SHA-256 hash. Before every command or
snapshot, replay all requests, compare computed state/results with stored versions,
and reconcile cash and equity. No cached in-memory balance is authoritative.

Hashes and triggers detect accidental corruption and inconsistent editing. They
are not signatures, a tamper-proof vault or protection against a file owner who
rewrites the entire history. Without an independently retained head hash, valid
tail truncation cannot be detected. Keep local backups using SQLite's backup
facilities or while all writers are stopped. Do not copy a changing database.

Replay validates this schema/reducer version; future accounting changes need
explicit migration/version handling. Full replay and per-event snapshots favor
auditability over throughput, so this foundation is intended for bounded local
experiments, not high-frequency workloads.

The SQLite ledger is authoritative for this stateful broker. The earlier JSONL
journal remains available for standalone research records; it is not automatically
written as a second accounting source. Generated databases and sidecar journals
are excluded by `.gitignore`.

## Next milestone

Connect causal Strategy Lab signals to this shared-cash broker in a deterministic
chronological replay coordinator. Define simultaneous-signal priority, next-open
entry ordering and end-of-run position policy, then compare desk variants under
identical portfolio limits. Keep it offline and paper-only.
