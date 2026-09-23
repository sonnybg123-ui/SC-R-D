import pytest

from sc_rd.backtest import Candle, resolve_plan
from sc_rd.models import TradePlan


def plan_long():
    return TradePlan("ABC", "long", 100, 95, 110, 20, "test")


def test_target_hit():
    candles = [Candle("t1", 100, 104, 98, 103), Candle("t2", 103, 111, 102, 110)]
    outcome = resolve_plan(plan_long(), candles)
    assert outcome.status == "target"
    assert outcome.realized_r == pytest.approx(2.0)


def test_stop_hit():
    candles = [Candle("t1", 100, 104, 94, 96)]
    outcome = resolve_plan(plan_long(), candles)
    assert outcome.status == "stop"
    assert outcome.realized_r == pytest.approx(-1.0)


def test_same_candle_is_conservative_by_default():
    candles = [Candle("t1", 100, 111, 94, 101)]
    outcome = resolve_plan(plan_long(), candles)
    assert outcome.status == "stop"
    assert outcome.realized_r == pytest.approx(-1.0)
    assert "ambiguity" in outcome.note


def test_same_candle_can_be_skipped():
    candles = [Candle("t1", 100, 111, 94, 101)]
    outcome = resolve_plan(plan_long(), candles, ambiguous_policy="skip")
    assert outcome.status == "ambiguous"
    assert outcome.realized_r is None
