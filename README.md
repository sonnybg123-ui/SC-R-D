# SC Trading R&D

SC Trading R&D is a research-first **paper-trading lab** for turning trading ideas into reproducible evidence, risk measurements, and lessons.

## Status

**Paper research platform with verified real-data smoke test and scheduled evidence runner**

The codebase deliberately has **no broker connection and no live-order path**. The first job is to learn what survives proper testing.

## What works now

- Risk-budget position sizing
- Stop distance, reward distance, and planned R:R
- Long and short paper-trade P&L / realized-R calculations
- JSONL paper-trade journal
- Win rate, average R, expectancy, profit factor, drawdown, and streak metrics
- Deterministic experiment IDs so changed assumptions cannot masquerade as the same test
- OHLC CSV loader
- Fixed-plan historical resolver with explicit same-candle ambiguity handling
- Five-desk R&D operating model: Vic, Alpha, Beta, Ben, Jah
- CLI tools
- Automated pytest suite
- GitHub Actions test workflow

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\\Scripts\\activate
pip install -e '.[dev]'
pytest -q
python scripts/demo.py
```

### Position-size a paper trade

```bash
python -m sc_rd plan ABC long 100 95 110 20 --setup "HH-HL continuation"
```

### Resolve a fixed plan against OHLC candles

```bash
python -m sc_rd resolve data/example_ohlc.csv ABC long 100 95 110 20
```

The resolver does **not** pretend to know the path inside an OHLC candle. If stop and target are both touched in the same candle, use an explicit policy: `conservative`, `optimistic`, or `skip`.

## Evidence rule

Every experiment should answer:

1. What exactly was the hypothesis?
2. What rules were frozen before the test?
3. What data and assumptions were used?
4. What was the planned risk?
5. What happened in R?
6. What was the drawdown / losing streak?
7. Where was the result ambiguous?
8. Did it survive out-of-sample testing?
9. What did we learn?
10. What experiment comes next?

## Repository map

```text
src/sc_rd/          core research code
scripts/            runnable demos
tests/              deterministic tests
data/               safe example/research data (no private exports)
docs/               roadmap and operating model
.github/workflows/  CI tests
```

## Safety boundary

Never commit API keys, passwords, broker credentials, account numbers, bank data, cookies, tokens, private account exports, or `.env` files to this public repository.

Live-money execution is intentionally out of scope until the paper-trading evidence base and controls are mature.

## Research scope and fill assumptions

The original fixed-plan resolver is a basic software-test tool. The later Strategy Lab, internal paper broker and chronological portfolio replay implement costs, causality and risk controls as described below. All five bots can run versioned internal-paper experiments; Vic is the sole department reporter. No live-money execution is available.

## Batch research pipeline

```bash
python -m sc_rd batch examples/batch.json --output reports
```

This offline synthetic example compares frozen Victor, Alpha and Beta plans.
Each run writes `results.json` and `report.md` into a SHA-256 run directory.
Dataset bytes, canonical method configuration and package source code determine
the run identity. Identical runs cannot overwrite existing evidence.

The pipeline validates chronological timezone-aware candles, applies explicit
fees/spread/slippage, prevents trades crossing from the in-sample period into
the holdout, and reports net R, unresolved outcomes and sample-size warnings.
It evaluates supplied plans; it does not claim those plans were selected without
hindsight, train strategies, or simulate a shared-capital portfolio.

See [batch research details](docs/BATCH_RESEARCH.md) for the input contract,
cost equations, limitations and reproducibility instructions.

## Strategy Lab: causal signals and walk-forward research

```bash
python -m sc_rd lab examples/strategy_lab.json --output reports
```

The synthetic example freezes Victor, Alpha and Beta rolling-range breakout
variants. Signals use completed candles; paper entries use the following open.
Rolling training windows choose candidates before each subsequent test window.
The final holdout stays hidden by default. An explicit `--include-holdout`
reveals only the final training-selected candidate and fixed baseline; once
viewed, that period is no longer an untouched sample.

See [Strategy Lab](docs/STRATEGY_LAB.md) for the exact rules, gaps, timeouts,
selection criteria, window reset assumptions and evidence limitations.

## Stateful paper broker and ledger

```bash
python -m sc_rd paper demo data/local/paper-demo.db
python -m sc_rd paper status data/local/paper-demo.db
python -m sc_rd paper audit data/local/paper-demo.db
```

The demo creates synthetic cash, executes a long and a collateralized short,
records a rejected order, processes exits and verifies the reloaded ledger.
Existing databases are never overwritten. Use a new filename for another demo.

The offline broker uses Decimal accounting, atomic SQLite events, idempotent
commands, cost-inclusive entry sizing and portfolio risk gates. Database files
remain local and ignored by Git. See [paper broker](docs/PAPER_BROKER.md) for
commands, collateral assumptions, reconciliation and limitations.

## Shared-cash chronological replay

```bash
python -m sc_rd portfolio examples/portfolio.json --output reports
```

This connects causal Strategy Lab signals to the persistent paper broker.
Allocations inside each portfolio compete for shared cash and risk capacity by
fixed priority. Separate baseline and mixed-desk experiments use identical limits.
Entries use next opens; no entry can spend profits from later in the same candle.
Each run produces audited SQLite ledgers, an equity curve, order/rejection traces,
JSON results and a Markdown comparison. The final holdout is excluded by default.

See [portfolio replay](docs/PORTFOLIO_REPLAY.md) for synchronized data requirements,
timing, holdout opt-in and explicit end-of-run position policies.

## Synthetic cloud workload (local preparation only)

The older synthetic cloud workflow is unpublished. Synthetic runs remain TEST_ONLY, not learning evidence. The real-data schedule is described in REAL_RESEARCH.md.

## Real-market data gateway

**Synthetic examples are software tests only: TEST_ONLY, never trading evidence.** Real research requires VERIFIED REAL datasets through `market-fetch`, `market-lab` or `market-portfolio`. The Twelve Data adapter performs strict single-session US OHLC/provenance/coverage checks and SHA-256 caching. It does not silently replace missing data with fixtures. See [gateway scope and usage](docs/MARKET_DATA.md).

The manual Twelve Data auth check succeeded using the existing `twelvedata_api` GitHub secret. The genuine AAPL smoke run passed on 24 September 2026; see REAL_RESEARCH.md for the fingerprint and limitations. T212 Demo authentication succeeded separately; read-only metadata integration and Practice order placement are NOT IMPLEMENTED. No live-money execution path exists. Canonical staff: Victor Price / Vic, Alpha, Beta, Benjamin Vale / Ben, Jah. Structure is a concept; ledger is software infrastructure.

The earlier hourly cloud runner remains local, unpublished work. Its synthetic outputs are TEST_ONLY. The scheduled real-data workflow runs historical paper experiments; no autonomous broker trading is enabled.

## Scheduled real-market paper experiments

The hourly GitHub Actions runner evaluates five versioned internal-paper experiments on REAL + VERIFIED AAPL data and preserves cumulative evidence for Vic, Alpha, Beta, Ben and Jah. Vic is the sole department reporter. This is historical research, not a new autonomous AI service or continuous forward account. See [operating model, artifacts and limits](REAL_RESEARCH.md). GBP conversion, catalyst data and automatic ChatGPT handoff remain unimplemented.

