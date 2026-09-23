from __future__ import annotations

import math

from .models import PaperTrade, TradePlan


def position_size(plan: TradePlan, *, fractional: bool = True) -> float:
    """Return quantity that keeps planned loss at or below the risk budget."""
    raw = plan.risk_budget / plan.risk_per_share
    return raw if fractional else float(math.floor(raw))


def cash_risk(plan: TradePlan, quantity: float) -> float:
    if not math.isfinite(quantity) or quantity <= 0:
        raise ValueError("quantity must be positive")
    return plan.risk_per_share * quantity


def pnl(trade: PaperTrade) -> float:
    direction = trade.plan.direction.lower()
    move = trade.exit_price - trade.plan.entry
    if direction == "short":
        move *= -1
    return move * trade.quantity


def realized_r(trade: PaperTrade) -> float:
    actual_risk = cash_risk(trade.plan, trade.quantity)
    return pnl(trade) / actual_risk
