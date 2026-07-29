from __future__ import annotations

import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")
    tmp.replace(path)


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str) + "\n")


def env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


class MT5DemoRuntime:
    def __init__(self) -> None:
        if os.getenv("LILITH_EXECUTION_MODE", "").strip().lower() != "mt5-demo":
            raise RuntimeError("Set LILITH_EXECUTION_MODE=mt5-demo.")
        if os.getenv("EDITH_MT5_CONFIRM_DEMO", "").strip().upper() != "YES":
            raise RuntimeError("Set EDITH_MT5_CONFIRM_DEMO=YES.")

        self.login = int(env("MT5_LOGIN"))
        self.password = env("MT5_PASSWORD")
        self.server = env("MT5_SERVER")
        self.symbol = os.getenv("EDITH_MT5_SYMBOL", "XAUUSDm")
        self.timeframe = os.getenv("EDITH_MT5_TIMEFRAME", "M5").upper()
        self.lot = float(os.getenv("EDITH_MT5_LOT", "0.01"))
        self.poll_seconds = max(1, int(os.getenv("EDITH_MT5_POLL_SECONDS", "15")))
        self.fast_period = max(2, int(os.getenv("EDITH_MT5_FAST_PERIOD", "5")))
        self.slow_period = max(3, int(os.getenv("EDITH_MT5_SLOW_PERIOD", "20")))
        self.stop_atr = float(os.getenv("EDITH_MT5_STOP_ATR", "1.5"))
        self.target_atr = float(os.getenv("EDITH_MT5_TARGET_ATR", "1.0"))
        self.max_positions = max(1, int(os.getenv("EDITH_MT5_MAX_POSITIONS", "1")))
        self.max_iterations = max(0, int(os.getenv("EDITH_MT5_MAX_ITERATIONS", "0")))
        self.magic = int(os.getenv("EDITH_MT5_MAGIC", "260729"))
        self.deviation = max(0, int(os.getenv("EDITH_MT5_DEVIATION", "20")))

        self.data_dir = Path("data")
        self.status_path = self.data_dir / "runtime_status.json"
        self.signals_path = self.data_dir / "signals.jsonl"
        self.orders_path = self.data_dir / "mt5_orders.jsonl"
        self.deals_path = self.data_dir / "mt5_deals.jsonl"
        self.session_id = str(uuid.uuid4())
        self.iteration = 0
        self.signals_seen = 0
        self.orders_sent = 0
        self.known_deals: set[int] = set()
        self.started_at = datetime.now(timezone.utc)
        self.mt5: Any = None

    def publish(self, **updates: Any) -> dict[str, Any]:
        current: dict[str, Any] = {}
        if self.status_path.exists():
            try:
                current = json.loads(self.status_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                pass
        current.update(updates)
        current["heartbeat_at"] = now()
        write_json(self.status_path, current)
        return current

    def connect(self) -> None:
        try:
            import MetaTrader5 as mt5
        except ImportError as exc:
            raise RuntimeError('Install MT5 support with: python -m pip install -e ".[mt5]"') from exc
        self.mt5 = mt5

        if not mt5.initialize():
            raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}")
        if not mt5.login(self.login, password=self.password, server=self.server):
            raise RuntimeError(f"MT5 login failed: {mt5.last_error()}")

        account = mt5.account_info()
        terminal = mt5.terminal_info()
        if account is None or terminal is None:
            raise RuntimeError(f"MT5 account/terminal info unavailable: {mt5.last_error()}")
        if int(account.login) != self.login:
            raise RuntimeError("Connected account does not match MT5_LOGIN.")
        if int(account.trade_mode) != int(getattr(mt5, "ACCOUNT_TRADE_MODE_DEMO", 0)):
            raise RuntimeError(f"Execution refused: account {account.login} is not an MT5 demo account.")
        if not terminal.connected or not terminal.trade_allowed:
            raise RuntimeError("MT5 is disconnected or algorithmic trading is disabled.")
        if not mt5.symbol_select(self.symbol, True):
            raise RuntimeError(f"Unable to select {self.symbol}: {mt5.last_error()}")

        self.publish(connection="Online", broker_connection="Connected", runtime="running", mode="mt5-demo",
                     session_id=self.session_id, started_at=now(), symbol=self.symbol, timeframe=self.timeframe,
                     account_login=int(account.login), account_server=str(account.server), account_trade_mode="demo",
                     account_balance=float(account.balance), account_equity=float(account.equity),
                     account_profit=float(account.profit), currency=str(account.currency), iteration=0,
                     signals_seen=0, orders_sent=0, open_positions=0, last_signal="HOLD",
                     message="Connected to MT5 demo account.")

    def timeframe_code(self) -> int:
        value = getattr(self.mt5, f"TIMEFRAME_{self.timeframe}", None)
        if value is None:
            raise RuntimeError(f"Unsupported timeframe: {self.timeframe}")
        return int(value)

    def market(self) -> tuple[float, float, float]:
        rates = self.mt5.copy_rates_from_pos(self.symbol, self.timeframe_code(), 0, max(60, self.slow_period + 10))
        if rates is None or len(rates) < self.slow_period + 2:
            raise RuntimeError(f"Insufficient MT5 rates for {self.symbol}: {self.mt5.last_error()}")
        closes = [float(row["close"]) for row in rates]
        highs = [float(row["high"]) for row in rates]
        lows = [float(row["low"]) for row in rates]
        fast = sum(closes[-self.fast_period:]) / self.fast_period
        slow = sum(closes[-self.slow_period:]) / self.slow_period
        tr = [max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1])) for i in range(1, len(closes))]
        atr = sum(tr[-14:]) / len(tr[-14:])
        return fast, slow, atr

    def signal(self, fast: float, slow: float, atr: float) -> dict[str, Any]:
        score = min(100.0, round(50.0 + (abs(fast - slow) / atr * 50.0 if atr > 0 else 0.0), 2))
        if fast > slow and score >= 60:
            side, decision = "BUY", "ENTER_MT5_DEMO"
        elif fast < slow and score >= 60:
            side, decision = "SELL", "ENTER_MT5_DEMO"
        else:
            side, decision = "HOLD", "SKIP"
        return {"timestamp": now(), "session_id": self.session_id, "iteration": self.iteration,
                "symbol": self.symbol, "timeframe": self.timeframe, "signal": side, "decision": decision,
                "score": score, "fast_sma": round(fast, 5), "slow_sma": round(slow, 5),
                "atr": round(atr, 5), "mode": "mt5-demo",
                "reason": "fast/slow SMA direction with ATR-normalised confidence"}

    def positions(self) -> list[Any]:
        return list(self.mt5.positions_get(symbol=self.symbol) or [])

    def send_order(self, side: str, atr: float) -> dict[str, Any] | None:
        owned = [p for p in self.positions() if int(getattr(p, "magic", 0)) == self.magic]
        if len(owned) >= self.max_positions:
            return None
        info = self.mt5.symbol_info(self.symbol)
        tick = self.mt5.symbol_info_tick(self.symbol)
        if info is None or tick is None:
            raise RuntimeError(f"Symbol information unavailable for {self.symbol}")

        volume = max(float(info.volume_min), min(float(info.volume_max), self.lot))
        step = float(info.volume_step)
        if step > 0:
            volume = round(round(volume / step) * step, 8)
        buy = side == "BUY"
        price = float(tick.ask if buy else tick.bid)
        digits = int(info.digits)
        request = {"action": self.mt5.TRADE_ACTION_DEAL, "symbol": self.symbol, "volume": volume,
                   "type": self.mt5.ORDER_TYPE_BUY if buy else self.mt5.ORDER_TYPE_SELL,
                   "price": round(price, digits),
                   "sl": round(price - atr*self.stop_atr if buy else price + atr*self.stop_atr, digits),
                   "tp": round(price + atr*self.target_atr if buy else price - atr*self.target_atr, digits),
                   "deviation": self.deviation, "magic": self.magic, "comment": "Edith MT5 demo",
                   "type_time": self.mt5.ORDER_TIME_GTC, "type_filling": self.mt5.ORDER_FILLING_IOC}

        check = self.mt5.order_check(request)
        if check is None or int(check.retcode) != 0:
            event = {"timestamp": now(), "session_id": self.session_id, "status": "rejected_check",
                     "side": side, "request": request, "retcode": None if check is None else int(check.retcode),
                     "comment": None if check is None else str(check.comment), "last_error": self.mt5.last_error()}
            append_jsonl(self.orders_path, event)
            return event

        result = self.mt5.order_send(request)
        ok_codes = {self.mt5.TRADE_RETCODE_DONE, self.mt5.TRADE_RETCODE_PLACED, self.mt5.TRADE_RETCODE_DONE_PARTIAL}
        event = {"timestamp": now(), "session_id": self.session_id,
                 "status": "accepted" if result is not None and result.retcode in ok_codes else "rejected_send",
                 "side": side, "symbol": self.symbol, "volume": volume, "price": request["price"],
                 "sl": request["sl"], "tp": request["tp"], "order": None if result is None else int(result.order),
                 "deal": None if result is None else int(result.deal), "retcode": None if result is None else int(result.retcode),
                 "comment": None if result is None else str(result.comment), "last_error": self.mt5.last_error()}
        append_jsonl(self.orders_path, event)
        if event["status"] == "accepted":
            self.orders_sent += 1
        return event

    def record_deals(self) -> int:
        deals = self.mt5.history_deals_get(self.started_at, datetime.now(timezone.utc), group=f"*{self.symbol}*") or []
        added = 0
        for deal in deals:
            ticket = int(deal.ticket)
            if ticket in self.known_deals or int(getattr(deal, "magic", 0)) != self.magic:
                continue
            self.known_deals.add(ticket)
            append_jsonl(self.deals_path, {"timestamp": datetime.fromtimestamp(int(deal.time), tz=timezone.utc).isoformat(),
                "session_id": self.session_id, "ticket": ticket, "order": int(deal.order),
                "position_id": int(deal.position_id), "symbol": str(deal.symbol), "entry": int(deal.entry),
                "volume": float(deal.volume), "price": float(deal.price), "profit": float(deal.profit),
                "commission": float(deal.commission), "swap": float(deal.swap), "fee": float(deal.fee),
                "comment": str(deal.comment), "magic": int(deal.magic), "mode": "mt5-demo"})
            added += 1
        return added

    def run(self) -> None:
        self.connect()
        print(f"Edith connected to MT5 demo account {self.login}.")
        try:
            while self.max_iterations <= 0 or self.iteration < self.max_iterations:
                self.iteration += 1
                fast, slow, atr = self.market()
                signal = self.signal(fast, slow, atr)
                append_jsonl(self.signals_path, signal)
                self.signals_seen += 1
                order = self.send_order(signal["signal"], atr) if signal["decision"] == "ENTER_MT5_DEMO" else None
                new_deals = self.record_deals()
                positions = self.positions()
                account = self.mt5.account_info()
                terminal = self.mt5.terminal_info()
                status = self.publish(connection="Online", broker_connection="Connected" if terminal and terminal.connected else "Disconnected",
                    runtime="running", mode="mt5-demo", session_id=self.session_id, symbol=self.symbol,
                    timeframe=self.timeframe, account_login=int(account.login) if account else None,
                    account_server=str(account.server) if account else None, account_trade_mode="demo",
                    account_balance=float(account.balance) if account else None, account_equity=float(account.equity) if account else None,
                    account_profit=float(account.profit) if account else None, currency=str(account.currency) if account else None,
                    iteration=self.iteration, signals_seen=self.signals_seen, orders_sent=self.orders_sent,
                    open_positions=len(positions), last_signal=signal["signal"], last_score=signal["score"],
                    last_order_status=None if order is None else order["status"], new_deals=new_deals,
                    message="MT5 demo telemetry received.")
                print(f"[{status['heartbeat_at']}] iteration={self.iteration} signal={signal['signal']} score={signal['score']} orders={self.orders_sent} positions={len(positions)}")
                time.sleep(self.poll_seconds)
        except KeyboardInterrupt:
            self.publish(connection="Offline", broker_connection="Disconnected", runtime="stopped", mode="mt5-demo",
                         session_id=self.session_id, stopped_at=now(), message="MT5 demo loop stopped by operator.")
            print("Edith MT5 demo loop stopped cleanly.")
        except Exception as exc:
            self.publish(connection="Error", broker_connection="Error", runtime="failed", mode="mt5-demo",
                         session_id=self.session_id, error=repr(exc), message="MT5 demo loop failed.")
            raise
        finally:
            if self.mt5 is not None:
                self.mt5.shutdown()


def run_from_environment() -> None:
    MT5DemoRuntime().run()
