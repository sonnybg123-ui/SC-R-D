from pathlib import Path
from uuid import uuid4

from sc_rd.journal import append_trade, load_trades, summarize
from sc_rd.models import PaperTrade, TradePlan
from sc_rd.risk import position_size, realized_r


journal = Path("data/local") / f"demo_{uuid4().hex}.jsonl"

plan = TradePlan(
    symbol="DEMO",
    direction="long",
    entry=100.0,
    stop=95.0,
    target=110.0,
    risk_budget=20.0,
    setup="HH-HL continuation",
    timeframe="15m",
)
qty = position_size(plan, fractional=False)
trade = PaperTrade(plan=plan, exit_price=110.0, quantity=qty, notes="Demo +2R")
append_trade(journal, trade)

print(f"Position size: {qty:g}")
print(f"Planned R:R: 1:{plan.planned_rr:.2f}")
print(f"Realized: {realized_r(trade):+.2f}R")
print(summarize(load_trades(journal)))
