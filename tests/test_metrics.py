import math

from sc_rd.metrics import performance_metrics


def test_metrics_drawdown_and_streaks():
    m = performance_metrics([1, 2, -1, -1, -1, 3, 0])
    assert m.trades == 7
    assert m.wins == 3
    assert m.losses == 3
    assert m.breakeven == 1
    assert m.max_winning_streak == 2
    assert m.max_losing_streak == 3
    assert m.max_drawdown_r == 3
    assert m.profit_factor == 2


def test_profit_factor_inf_without_losses():
    m = performance_metrics([1, 2])
    assert math.isinf(m.profit_factor)
