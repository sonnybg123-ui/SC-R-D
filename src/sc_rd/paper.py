"""Offline paper broker: Decimal accounting and an atomic replayable SQLite ledger."""
from __future__ import annotations

import copy
import json
import sqlite3
from dataclasses import asdict, dataclass
from decimal import Decimal, ROUND_DOWN, localcontext
from pathlib import Path

from .backtest import Candle
from .desks import DESKS
from .models import TradePlan
from .metrics import performance_metrics
from .research import Costs, canonical, digest, instant


D = Decimal
STEP = D("0.000001")
ZERO = D(0)


def number(value: object, *, positive: bool = True) -> Decimal:
    if isinstance(value, bool):
        raise ValueError("boolean is not an amount")
    try:
        result = D(str(value))
    except Exception as exc:
        raise ValueError("invalid decimal amount") from exc
    if not result.is_finite() or abs(result) > D("1e12") or result < 0 or (positive and result == 0):
        raise ValueError("amount must be finite, nonnegative and at most 1e12; positive where required")
    if result and result < D("1e-12"):
        raise ValueError("amount below supported precision")
    return result


def text(value: Decimal) -> str:
    return format(value, "f")


@dataclass(frozen=True)
class Limits:
    max_trade_risk: float = 100
    max_total_risk: float = 300
    max_gross_exposure: float = 10000
    max_positions: int = 3
    max_drawdown: float = 500
    max_mark_age_seconds: int = 3600

    def __post_init__(self) -> None:
        for key, value in asdict(self).items():
            if key in {"max_positions", "max_mark_age_seconds"}:
                if type(value) is not int or value < 1:
                    raise ValueError(f"{key} must be a positive integer")
            else:
                number(value)


def side_cost(state: dict, price: Decimal, quantity: Decimal) -> Decimal:
    c = state["costs"]
    rate = (D(c["fee_bps"]) + D(c["spread_bps"]) / 2 + D(c["slippage_bps"])) / 10000
    return D(c["fee_per_side"]) + price * quantity * rate


def balances(state: dict) -> dict:
    long_value = short_value = open_gross = entry_fees = exit_reserve = risk = ZERO
    for p in state["positions"].values():
        qty, entry = D(p["quantity"]), D(p["entry"])
        mark = D(state["marks"][p["symbol"]]["price"])
        sign = 1 if p["direction"] == "long" else -1
        if sign == 1:
            long_value += mark * qty
        else:
            short_value += mark * qty
        open_gross += sign * (mark - entry) * qty
        entry_fees += D(p["entry_fee"])
        exit_reserve += side_cost(state, mark, qty)
        risk += D(p["reserved_risk"])
    cash = D(state["cash"])
    equity = cash + long_value - short_value
    realized = sum((D(t["net_pnl"]) for t in state["closed"]), ZERO)
    expected = D(state["initial_cash"]) + realized + open_gross - entry_fees
    if abs(equity - expected) > D("1e-18"):
        raise ValueError("ledger reconciliation failed")
    peak = max(D(state["peak_equity"]), equity)
    return {"cash": text(cash), "equity": text(equity), "long_market_value": text(long_value),
            "short_liability": text(short_value), "short_collateral": text(2 * short_value),
            "exit_cost_reserve": text(exit_reserve), "available_cash": text(cash - 2 * short_value - exit_reserve),
            "gross_exposure": text(long_value + short_value), "reserved_risk": text(risk),
            "realized_net_pnl": text(realized), "unrealized_gross_pnl": text(open_gross),
            "open_entry_costs": text(entry_fees), "fees_paid": state["fees_paid"],
            "drawdown": text(peak - equity), "peak_equity": text(peak)}


def refresh(state: dict) -> None:
    b = balances(state)
    state["peak_equity"] = b["peak_equity"]
    if D(b["drawdown"]) >= D(str(state["limits"]["max_drawdown"])) or D(b["equity"]) <= 0:
        state["halted"] = True  # No reset command: preserve the research failure.


def rejected(state: dict, reason: str) -> tuple[dict, dict]:
    return state, {"status": "rejected", "reason": reason, "cash_delta": "0"}


def close_position(state: dict, position_id: str, price: Decimal, at: str, reason: str) -> dict:
    p = state["positions"].pop(position_id)
    qty, entry = D(p["quantity"]), D(p["entry"])
    sign = 1 if p["direction"] == "long" else -1
    fee = side_cost(state, price, qty)
    cash_delta = sign * price * qty - fee
    net = sign * (price - entry) * qty - D(p["entry_fee"]) - fee
    state["cash"] = text(D(state["cash"]) + cash_delta)
    state["fees_paid"] = text(D(state["fees_paid"]) + fee)
    closed = p | {"position_id": position_id, "exit_price": text(price), "exit_fee": text(fee),
                  "closed_at": at, "reason": reason, "net_pnl": text(net),
                  "net_r": text(net / D(p["gross_initial_risk"]))}
    state["closed"].append(closed)
    return {"status": "closed", "trade": closed, "cash_delta": text(cash_delta)}


def apply_bar(state: dict, symbol: str, candle: dict, at: str) -> dict:
    if not isinstance(symbol, str) or not symbol.strip():
        raise ValueError("nonempty bar symbol required")
    if symbol in state["last_bars"] and instant(at) <= instant(state["last_bars"][symbol]):
        return {"status": "rejected", "reason": "candle already processed", "cash_delta": "0"}
    op, high, low, close = (number(candle[key]) for key in ("open", "high", "low", "close"))
    if not (low <= op <= high and low <= close <= high):
        raise ValueError("invalid OHLC range")
    exits = []
    for pid, pos in list(state["positions"].items()):
        if pos["symbol"] != symbol:
            continue
        stop, target = D(pos["stop"]), D(pos["target"])
        long = pos["direction"] == "long"
        stop_gap = op <= stop if long else op >= stop
        target_gap = op >= target if long else op <= target
        hit_stop = low <= stop if long else high >= stop
        hit_target = high >= target if long else low <= target
        if stop_gap:
            exits.append(close_position(state, pid, op, at, "opening-gap-stop"))
        elif target_gap:
            exits.append(close_position(state, pid, target, at, "opening-target"))
        elif hit_stop:
            reason = "ambiguous-conservative-stop" if hit_target else "stop"
            exits.append(close_position(state, pid, stop, at, reason))
        elif hit_target:
            exits.append(close_position(state, pid, target, at, "target"))
    state["last_bars"][symbol] = at
    state["marks"][symbol] = {"price": text(close), "at": at}
    result = {"status": "processed", "exits": exits,
              "cash_delta": text(sum((D(e["cash_delta"]) for e in exits), ZERO))}
    return result


def reduce_event(previous: dict | None, request: dict) -> tuple[dict, dict]:
    """Pure reducer; the same requests must reproduce every stored snapshot."""
    with localcontext() as context:
        context.prec = 40
        return _reduce(previous, request)


def _reduce(previous: dict | None, r: dict) -> tuple[dict, dict]:
    if r["kind"] == "init":
        if previous is not None or r["version"] != 1 or r["mode"] != "paper-only":
            raise ValueError("invalid paper ledger initialization")
        cash = number(r["initial_cash"])
        Limits(**r["limits"])
        costs = {k: text(number(v, positive=False)) for k, v in r["costs"].items()}
        if set(costs) != {"fee_per_side", "fee_bps", "spread_bps", "slippage_bps"}:
            raise ValueError("invalid cost configuration")
        if (D(costs["fee_bps"]) + D(costs["spread_bps"]) / 2 + D(costs["slippage_bps"])) >= 10000:
            raise ValueError("combined per-side cost rate must be below 100%")
        state = {"mode": "paper-only", "initial_cash": text(cash), "cash": text(cash),
                 "costs": costs, "limits": r["limits"], "positions": {}, "closed": [], "marks": {},
                 "last_bars": {}, "fees_paid": "0", "peak_equity": text(cash), "halted": False, "last_at": r["at"]}
        return state, {"status": "initialized", "cash_delta": text(cash)}
    if previous is None:
        raise ValueError("ledger is not initialized")
    state = copy.deepcopy(previous)
    if instant(r["at"]) < instant(state["last_at"]):
        raise ValueError("event time cannot move backwards")
    state["last_at"] = r["at"]
    kind = r["kind"]
    if kind == "open":
        p = r["plan"]
        direction = p["direction"].lower()
        symbol = p["symbol"]
        if not isinstance(symbol, str) or not symbol.strip() or direction not in {"long", "short"}:
            raise ValueError("valid symbol and long/short direction required")
        if r["desk"] not in DESKS:
            raise ValueError("unknown research desk")
        entry, stop, target, budget = (number(p[k]) for k in ("entry", "stop", "target", "risk_budget"))
        if not (stop < entry < target if direction == "long" else target < entry < stop):
            raise ValueError("invalid plan price geometry")
        if state["halted"]:
            return rejected(state, "drawdown/insolvency halt: new positions disabled")
        if symbol in state["last_bars"] and instant(r["at"]) <= instant(state["last_bars"][symbol]):
            return rejected(state, "cannot enter at or before an already processed candle")
        if any(pos["symbol"] == symbol for pos in state["positions"].values()):
            return rejected(state, "one position per symbol; no hedging or pyramiding")
        if len(state["positions"]) >= state["limits"]["max_positions"]:
            return rejected(state, "maximum position count reached")
        for pos in state["positions"].values():
            age = (instant(r["at"]) - instant(state["marks"][pos["symbol"]]["at"])).total_seconds()
            if age > state["limits"]["max_mark_age_seconds"]:
                return rejected(state, "stale portfolio mark; refresh before new risk")
        cap = min(budget, D(str(state["limits"]["max_trade_risk"])))
        fixed = 2 * D(state["costs"]["fee_per_side"])
        distance = abs(entry - stop)
        unit_cost = side_cost(state, entry, D(1)) + side_cost(state, stop, D(1)) - fixed
        if r["quantity"] is None:
            qty = ((cap - fixed) / (distance + unit_cost)).quantize(STEP, rounding=ROUND_DOWN)
            if qty <= 0:
                return rejected(state, "risk budget cannot cover costs and minimum quantity")
        else:
            qty = number(r["quantity"])
            if qty != qty.quantize(STEP, rounding=ROUND_DOWN):
                raise ValueError("quantity must be a multiple of 0.000001")
        entry_fee = side_cost(state, entry, qty)
        reserved = distance * qty + entry_fee + side_cost(state, stop, qty)
        if reserved > cap:
            return rejected(state, "cost-inclusive per-trade risk limit exceeded")
        before = balances(state)
        if D(before["reserved_risk"]) + reserved > D(str(state["limits"]["max_total_risk"])):
            return rejected(state, "portfolio risk limit exceeded")
        candidate = copy.deepcopy(state)
        sign = 1 if direction == "long" else -1
        cash_delta = -sign * entry * qty - entry_fee
        candidate["cash"] = text(D(candidate["cash"]) + cash_delta)
        candidate["fees_paid"] = text(D(candidate["fees_paid"]) + entry_fee)
        candidate["marks"][symbol] = {"price": text(entry), "at": r["at"]}
        position = {"symbol": symbol, "direction": direction, "entry": text(entry), "stop": text(stop),
                    "target": text(target), "risk_budget": text(budget), "quantity": text(qty),
                    "entry_fee": text(entry_fee), "gross_initial_risk": text(distance * qty),
                    "reserved_risk": text(reserved), "desk": r["desk"], "opened_at": r["at"],
                    "setup": p["setup"], "timeframe": p.get("timeframe", "dataset-bars")}
        candidate["positions"][r["id"]] = position
        after = balances(candidate)
        if D(after["available_cash"]) < 0:
            return rejected(state, "insufficient unreserved cash including short collateral and exit costs")
        if D(after["gross_exposure"]) > D(str(state["limits"]["max_gross_exposure"])):
            return rejected(state, "gross exposure limit exceeded")
        refresh(candidate)
        if candidate["halted"]:
            return rejected(state, "entry costs would breach drawdown/solvency limit")
        return candidate, {"status": "filled", "position_id": r["id"], "position": position, "cash_delta": text(cash_delta)}
    if kind == "close":
        price = number(r["price"])
        if r["position_id"] not in state["positions"]:
            return rejected(state, "position is not open")
        result = close_position(state, r["position_id"], price, r["at"], r.get("reason", "manual-paper-exit"))
    elif kind == "mark":
        if not r["prices"]:
            raise ValueError("at least one mark required")
        for symbol, price in r["prices"].items():
            if not isinstance(symbol, str) or not symbol.strip():
                raise ValueError("nonempty mark symbol required")
            state["marks"][symbol] = {"price": text(number(price)), "at": r["at"]}
        result = {"status": "marked", "cash_delta": "0"}
    elif kind == "bar":
        result = apply_bar(state, r["symbol"], r["candle"], r["at"])
        if result["status"] == "rejected":
            return state, result
    elif kind == "bars":
        if not isinstance(r["candles"], dict) or not r["candles"]:
            raise ValueError("nonempty candle mapping required")
        # Reject the entire batch before any symbol can mutate state.
        for symbol in r["candles"]:
            if symbol in state["last_bars"] and instant(r["at"]) <= instant(state["last_bars"][symbol]):
                return rejected(state, "candle already processed")
        outcomes = {symbol: apply_bar(state, symbol, r["candles"][symbol], r["at"])
                    for symbol in sorted(r["candles"])}
        result = {"status": "processed", "bars": outcomes,
                  "cash_delta": text(sum((D(o["cash_delta"]) for o in outcomes.values()), ZERO))}
    else:
        raise ValueError("unsupported paper command")
    refresh(state)
    return state, result


def replay(rows: list) -> tuple[dict | None, str]:
    state, previous_hash = None, "0" * 64
    cash_sum = ZERO
    with localcontext() as context:
        context.prec = 40
        for expected, row in enumerate(rows, 1):
            seq, command_id, request_json, result_json, state_json, parent, event_hash = row
            body = {"seq": seq, "id": command_id, "request": request_json, "result": result_json,
                    "state": state_json, "previous": parent}
            if seq != expected or parent != previous_hash or digest(canonical(body).encode()) != event_hash:
                raise ValueError("ledger sequence/hash verification failed")
            request = json.loads(request_json)
            if request["id"] != command_id:
                raise ValueError("ledger command identity mismatch")
            state, result = reduce_event(state, request)
            if canonical(state) != state_json or canonical(result) != result_json:
                raise ValueError("ledger replay differs from stored accounting")
            cash_sum += D(result["cash_delta"])
            if abs(cash_sum - D(state["cash"])) > D("1e-18"):
                raise ValueError("cash-flow reconciliation failed")
            previous_hash = event_hash
    return state, previous_hash


class PaperBroker:
    """Every command is local, idempotent and committed in one SQLite transaction."""

    def __init__(self, path: str | Path):
        self.path = Path(path).resolve()
        if not self.path.is_file():
            raise FileNotFoundError("paper ledger does not exist; initialize explicitly")

    @classmethod
    def create(cls, path: str | Path, *, initial_cash: float, limits: Limits, costs: Costs, at: str) -> "PaperBroker":
        request = {"kind": "init", "id": "initialization", "version": 1, "mode": "paper-only",
                   "initial_cash": str(initial_cash), "limits": asdict(limits), "costs": asdict(costs),
                   "at": instant(at).isoformat()}
        state, result = reduce_event(None, request)  # Validate before creating a file.
        target = Path(path).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb"):
            pass  # Never overwrite an existing ledger.
        broker = cls(target)
        connection = broker._connect()
        try:
            connection.executescript("""
                CREATE TABLE events (
                    seq INTEGER PRIMARY KEY, command_id TEXT NOT NULL UNIQUE,
                    request_json TEXT NOT NULL, result_json TEXT NOT NULL, state_json TEXT NOT NULL,
                    previous_hash TEXT NOT NULL, event_hash TEXT NOT NULL);
                CREATE TRIGGER no_update BEFORE UPDATE ON events BEGIN SELECT RAISE(ABORT, 'append-only ledger'); END;
                CREATE TRIGGER no_delete BEFORE DELETE ON events BEGIN SELECT RAISE(ABORT, 'append-only ledger'); END;
            """)
            connection.execute("BEGIN IMMEDIATE")
            broker._append(connection, 1, request, result, state, "0" * 64)
            connection.commit()
        finally:
            connection.close()
        return broker

    def _connect(self):
        connection = None
        try:
            connection = sqlite3.connect(self.path.as_uri() + "?mode=rw", uri=True, timeout=10)
            connection.execute("PRAGMA synchronous=FULL")
            return connection
        except sqlite3.Error as exc:
            if connection is not None:
                connection.close()
            raise ValueError(f"cannot open paper ledger: {exc}") from exc

    @staticmethod
    def _append(connection, seq, request, result, state, parent):
        request_json, result_json, state_json = map(canonical, (request, result, state))
        body = {"seq": seq, "id": request["id"], "request": request_json,
                "result": result_json, "state": state_json, "previous": parent}
        connection.execute("INSERT INTO events VALUES (?, ?, ?, ?, ?, ?, ?)",
                           (seq, request["id"], request_json, result_json, state_json, parent, digest(canonical(body).encode())))

    def _command(self, kind: str, command_id: str, at: str, **payload) -> dict:
        if not isinstance(command_id, str) or not command_id.strip() or len(command_id) > 120:
            raise ValueError("command_id must contain 1 to 120 characters")
        request = {"kind": kind, "id": command_id, "at": instant(at).isoformat(), **payload}
        canonical(request)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute("SELECT * FROM events ORDER BY seq").fetchall()
            state, parent = replay(rows)
            if state is None:
                raise ValueError("ledger is not initialized")
            for row in rows:
                if row[1] == command_id:
                    if row[2] != canonical(request):
                        raise ValueError("command_id was already used for a different request")
                    return json.loads(row[3])
            state, result = reduce_event(state, request)
            self._append(connection, len(rows) + 1, request, result, state, parent)
            connection.commit()
            return result
        except sqlite3.Error as exc:
            raise ValueError(f"paper ledger transaction failed: {exc}") from exc
        finally:
            connection.rollback()
            connection.close()

    def open(self, plan: TradePlan, *, command_id: str, at: str, desk: str = "victor", quantity: float | None = None) -> dict:
        return self._command("open", command_id, at, plan=asdict(plan), desk=desk,
                             quantity=None if quantity is None else str(quantity))

    def close(self, position_id: str, price: float, *, command_id: str, at: str, reason: str | None = None) -> dict:
        payload = {} if reason is None else {"reason": reason}
        if reason is not None and reason not in {"replay-opening-gap-stop", "replay-opening-target", "replay-timeout", "replay-end"}:
            raise ValueError("unsupported paper exit reason")
        return self._command("close", command_id, at, position_id=position_id, price=str(price), **payload)

    def mark(self, prices: dict, *, command_id: str, at: str) -> dict:
        if not isinstance(prices, dict):
            raise ValueError("marks must be a symbol-to-price mapping")
        return self._command("mark", command_id, at, prices={s: str(p) for s, p in prices.items()})

    def process_bar(self, symbol: str, candle: Candle, *, command_id: str) -> dict:
        values = asdict(candle)
        values.pop("timestamp")
        return self._command("bar", command_id, candle.timestamp, symbol=symbol, candle=values)

    def process_bars(self, candles: dict[str, Candle], *, command_id: str) -> dict:
        if not isinstance(candles, dict) or not candles:
            raise ValueError("nonempty candle mapping required")
        times = {instant(c.timestamp) for c in candles.values()}
        if len(times) != 1:
            raise ValueError("batch candles must have the same timestamp")
        values = {symbol: {k: v for k, v in asdict(c).items() if k != "timestamp"}
                  for symbol, c in candles.items()}
        return self._command("bars", command_id, next(iter(times)).isoformat(), candles=values)

    def snapshot(self) -> dict:
        connection = self._connect()
        try:
            rows = connection.execute("SELECT * FROM events ORDER BY seq").fetchall()
            state, head = replay(rows)
            if state is None:
                raise ValueError("ledger is not initialized")
            with localcontext() as context:
                context.prec = 40
                book = balances(state)
                flags = []
                if state["halted"]:
                    flags.append("new-entry halt is latched")
                if D(book["available_cash"]) < 0:
                    flags.append("cash/collateral/exit-cost reserve deficit")
                if D(book["gross_exposure"]) > D(str(state["limits"]["max_gross_exposure"])):
                    flags.append("marked gross exposure exceeds limit")
                for pos in state["positions"].values():
                    age = (instant(state["last_at"]) - instant(state["marks"][pos["symbol"]]["at"])).total_seconds()
                    if age > state["limits"]["max_mark_age_seconds"]:
                        flags.append(f"stale mark: {pos['symbol']}")
                metrics = asdict(performance_metrics(float(t["net_r"]) for t in state["closed"]))
                if metrics["profit_factor"] == float("inf"):
                    metrics["profit_factor"] = "infinite"
                return {"state": state, "balances": book, "event_count": len(rows),
                        "ledger_head": head, "reconciled": True, "risk_flags": flags,
                        "closed_trade_net_r_metrics": metrics}
        except sqlite3.Error as exc:
            raise ValueError(f"paper ledger read failed: {exc}") from exc
        finally:
            connection.close()
