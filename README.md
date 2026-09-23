# SC Trading R&D

SC Trading R&D is a research-first **paper-trading lab** for turning trading ideas into reproducible evidence, risk measurements, and lessons.

## Status

**Phase 1 — Foundation: operational locally**

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
- Five-desk R&D operating model: Victor, Alpha, Beta, Structure, Ledger
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

This foundation implements sizing, paper-trade records, historical fixed-plan
resolution and analysis. It is not yet a scanner, autonomous desk, portfolio risk
manager, or event-driven paper broker. Desks currently define research roles.

The historical resolver assumes an existing position before the supplied candles.
Supply chronological, unique candles from one instrument. A stop crossed at the
open fills at that open (losses may exceed 1R); a target crossed at the open fills
at the target without favorable price improvement. Other same-candle conflicts
use the chosen ambiguity policy. Fees, spreads, liquidity and further slippage
are not modelled. Results are gross research estimates, not execution guarantees.
R uses initial stop distance times actual quantity, not the unused risk budget.
Profit factor is calculated in R, not cash. No broker or external data connection
is included. Keep local journals and private datasets outside version control.

Target architecture:
Market Data -> Scanner -> Strategy Lab -> Victor / Alpha / Beta experiments ->
Risk Engine -> Paper Broker -> Ledger -> Performance Analysis -> Research Conclusions.

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
