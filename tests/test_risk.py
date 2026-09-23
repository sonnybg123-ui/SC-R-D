import pytest

from sc_rd.models import PaperTrade, TradePlan
from sc_rd.risk import cash_risk, position_size, realized_r


def test_position_size_matches_risk_budget():
    plan = TradePlan("ABC", "long", 100, 95, 110, 20, "test")
    qty = position_size(plan, fractional=False)
    assert qty == 4
    assert cash_risk(plan, qty) == 20


def test_two_r_winner():
    plan = TradePlan("ABC", "long", 100, 95, 110, 20, "test")
    trade = PaperTrade(plan=plan, exit_price=110, quantity=4)
    assert realized_r(trade) == pytest.approx(2.0)


def test_one_r_loss():
    plan = TradePlan("ABC", "long", 100, 95, 110, 20, "test")
    trade = PaperTrade(plan=plan, exit_price=95, quantity=4)
    assert realized_r(trade) == pytest.approx(-1.0)


def test_short_trade():
    plan = TradePlan("ABC", "short", 100, 105, 90, 20, "test")
    trade = PaperTrade(plan=plan, exit_price=90, quantity=4)
    assert realized_r(trade) == pytest.approx(2.0)
