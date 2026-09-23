from sc_rd.journal import append_trade, load_trades, summarize
from sc_rd.models import PaperTrade, TradePlan


def test_journal_round_trip(tmp_path):
    path = tmp_path / "journal.jsonl"
    plan = TradePlan("ABC", "long", 100, 95, 110, 20, "test")
    append_trade(path, PaperTrade(plan, 110, 4, notes="winner"))
    append_trade(path, PaperTrade(plan, 95, 4, notes="loser"))

    trades = load_trades(path)
    stats = summarize(trades)
    assert len(trades) == 2
    assert stats.trades == 2
    assert stats.wins == 1
    assert stats.losses == 1
    assert stats.average_r == 0.5
