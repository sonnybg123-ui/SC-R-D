"""Local CLI for synthetic paper accounts; never accepts broker credentials."""
import json
from pathlib import Path

from .backtest import Candle
from .models import TradePlan
from .paper import Limits, PaperBroker
from .research import Costs


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def demo(path):
    broker = PaperBroker.create(path, initial_cash=10000, costs=Costs(.1, 1, 2, 1),
                               limits=Limits(25, 50, 2000, 2, 500, 3600), at="2026-01-01T09:00:00Z")
    broker.open(TradePlan("SYNTH-L", "long", 100, 95, 110, 20, "synthetic"),
                command_id="demo-long", at="2026-01-01T09:00:00Z")
    broker.open(TradePlan("SYNTH-S", "short", 100, 105, 90, 20, "synthetic"),
                command_id="demo-short", at="2026-01-01T09:00:00Z", desk="beta")
    rejected = broker.open(TradePlan("SYNTH-X", "long", 100, 95, 110, 20, "synthetic"),
                           command_id="demo-limit-check", at="2026-01-01T09:00:00Z")
    broker.mark({"SYNTH-L": 102, "SYNTH-S": 98}, command_id="demo-marks", at="2026-01-01T09:05:00Z")
    broker.process_bar("SYNTH-L", Candle("2026-01-01T09:15:00Z", 102, 111, 101, 110), command_id="demo-long-bar")
    broker.process_bar("SYNTH-S", Candle("2026-01-01T09:15:00Z", 98, 99, 89, 90), command_id="demo-short-bar")
    result = PaperBroker(path).snapshot()
    if rejected["status"] != "rejected" or result["state"]["positions"] or len(result["state"]["closed"]) != 2:
        raise ValueError("synthetic paper demo failed")
    return result


def execute(args):
    action = args.paper_action
    if action == "init":
        config = load(args.config)
        if set(config) != {"limits", "costs"}:
            raise ValueError("paper config requires exactly limits and costs")
        result = PaperBroker.create(args.database, initial_cash=args.cash, limits=Limits(**config["limits"]),
                                    costs=Costs(**config["costs"]), at=args.at).snapshot()
    elif action == "demo":
        result = demo(args.database)
    else:
        broker = PaperBroker(args.database)
        if action == "open":
            result = broker.open(TradePlan(**load(args.plan)), command_id=args.id, at=args.at,
                                 desk=args.desk, quantity=args.quantity)
        elif action == "close":
            result = broker.close(args.position, args.price, command_id=args.id, at=args.at)
        elif action == "mark":
            result = broker.mark(load(args.prices), command_id=args.id, at=args.at)
        elif action == "bar":
            result = broker.process_bar(args.symbol, Candle(**load(args.candle)), command_id=args.id)
        else:
            result = broker.snapshot()
            if action == "audit":
                result.pop("state")
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
    if result.get("status") == "rejected":
        raise SystemExit(2)


def configure(subs):
    paper = subs.add_parser("paper", help="offline paper broker and replayable SQLite ledger")
    actions = paper.add_subparsers(dest="paper_action", required=True)
    for action in ("init", "open", "close", "mark", "bar", "status", "audit", "demo"):
        parser = actions.add_parser(action)
        parser.add_argument("database", type=Path)
        parser.set_defaults(func=execute)
        if action == "init":
            parser.add_argument("--cash", required=True, help="synthetic starting cash")
            parser.add_argument("--config", type=Path, required=True)
        if action in {"init", "open", "close", "mark"}:
            parser.add_argument("--at", required=True, help="timezone-aware research timestamp")
        if action in {"open", "close", "mark", "bar"}:
            parser.add_argument("--id", required=True, help="unique idempotency identifier")
        if action == "open":
            parser.add_argument("plan", type=Path)
            parser.add_argument("--desk", default="victor")
            parser.add_argument("--quantity", help="optional explicit quantity; otherwise cost-aware sizing")
        elif action == "close":
            parser.add_argument("position")
            parser.add_argument("--price", required=True)
        elif action == "mark":
            parser.add_argument("prices", type=Path)
        elif action == "bar":
            parser.add_argument("symbol")
            parser.add_argument("candle", type=Path)
