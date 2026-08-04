from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")
    try:
        tmp.replace(path)
    except PermissionError:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        try:
            tmp.replace(path)
        except PermissionError:
            path.write_text(tmp.read_text(encoding="utf-8"), encoding="utf-8")
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str) + "\n")


def env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


@dataclass(frozen=True)
class MarketSnapshot:
    candle_time: int
    fast: float
    slow: float
    atr: float
    close: float


class SpreadGateRejected(RuntimeError):
    def __init__(self, metadata: dict[str, Any]) -> None:
        self.metadata = metadata
        super().__init__(str(metadata.get("rejection_reason", "spread_gate_rejected")))


class RuntimeLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.fd: int | None = None

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
        try:
            self.fd = os.open(self.path, flags)
        except FileExistsError as exc:
            raise RuntimeError(f"Another Edith runtime appears active: {self.path}") from exc
        os.write(self.fd, f"pid={os.getpid()} started={now()}\n".encode())

    def release(self) -> None:
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass


class MT5DemoRuntime:
    def __init__(self, mt5: Any | None = None, data_dir: str | Path = "data") -> None:
        if os.getenv("LILITH_EXECUTION_MODE", "").strip().lower() != "mt5-demo":
            raise RuntimeError("Set LILITH_EXECUTION_MODE=mt5-demo.")
        if os.getenv("EDITH_MT5_CONFIRM_DEMO", "").strip().upper() != "YES":
            raise RuntimeError("Set EDITH_MT5_CONFIRM_DEMO=YES.")

        self.login = int(env("MT5_LOGIN"))
        self.password = env("MT5_PASSWORD")
        self.server = env("MT5_SERVER")
        self.symbol = os.getenv("EDITH_MT5_SYMBOL", "XAUUSDm")
        self.timeframe = os.getenv("EDITH_MT5_TIMEFRAME", "M5").upper()
        self.requested_lot = float(os.getenv("EDITH_MT5_LOT", "0.01"))
        self.poll_seconds = max(1, int(os.getenv("EDITH_MT5_POLL_SECONDS", "15")))
        self.fast_period = max(2, int(os.getenv("EDITH_MT5_FAST_PERIOD", "5")))
        self.slow_period = max(self.fast_period + 1, int(os.getenv("EDITH_MT5_SLOW_PERIOD", "20")))
        self.stop_atr = max(0.1, float(os.getenv("EDITH_MT5_STOP_ATR", "1.5")))
        self.target_atr = max(0.1, float(os.getenv("EDITH_MT5_TARGET_ATR", "1.0")))
        self.max_positions = max(1, int(os.getenv("EDITH_MT5_MAX_POSITIONS", "1")))
        self.max_iterations = max(0, int(os.getenv("EDITH_MT5_MAX_ITERATIONS", "0")))
        self.magic = int(os.getenv("EDITH_MT5_MAGIC", "260729"))
        self.deviation = max(0, int(os.getenv("EDITH_MT5_DEVIATION", "20")))
        self.max_risk_cash = max(0.01, float(os.getenv("EDITH_MT5_MAX_RISK_CASH", "1.00")))
        self.max_risk_pct = max(0.01, float(os.getenv("EDITH_MT5_MAX_RISK_PCT", "2.0")))
        self.max_daily_loss = max(0.01, float(os.getenv("EDITH_MT5_MAX_DAILY_LOSS", "5.00")))
        self.max_drawdown_pct = max(0.01, float(os.getenv("EDITH_MT5_MAX_DRAWDOWN_PCT", "10.0")))
        self.min_margin_level = max(1.0, float(os.getenv("EDITH_MT5_MIN_MARGIN_LEVEL", "300")))
        self.max_spread_points = max(1.0, float(os.getenv("EDITH_MT5_MAX_SPREAD_POINTS", "80")))
        self.high_grade_score = max(0.0, float(os.getenv("EDITH_MT5_HIGH_GRADE_SCORE", "85")))
        self.high_grade_max_spread_points = max(1.0, float(os.getenv("EDITH_MT5_HIGH_GRADE_MAX_SPREAD_POINTS", "260")))
        self.high_grade_max_spread_atr_fraction = max(0.0, float(os.getenv("EDITH_MT5_HIGH_GRADE_MAX_SPREAD_ATR_FRACTION", "0.07")))
        self.high_grade_rearm_score = max(0.0, float(os.getenv("EDITH_MT5_HIGH_GRADE_REARM_SCORE", "70")))
        self.high_grade_one_per_regime = os.getenv("EDITH_MT5_HIGH_GRADE_ONE_PER_REGIME", "YES").strip().upper() not in {"0", "NO", "FALSE", "OFF"}

        self.data_dir = Path(data_dir)
        self.status_path = self.data_dir / "runtime_status.json"
        self.signals_path = self.data_dir / "signals.jsonl"
        self.orders_path = self.data_dir / "mt5_orders.jsonl"
        self.deals_path = self.data_dir / "mt5_deals.jsonl"
        self.state_path = self.data_dir / "mt5_runtime_state.json"
        self.lock = RuntimeLock(self.data_dir / "edith_mt5.lock")
        self.session_id = str(uuid.uuid4())
        self.iteration = 0
        self.signals_seen = 0
        self.orders_sent = 0
        self.started_at = datetime.now(timezone.utc)
        self.mt5 = mt5
        self.initial_equity = 0.0
        self.last_candle_time: int | None = None
        self.last_signal_key: str | None = None
        self.known_deals: set[int] = set()
        self.high_grade_regime_direction: str | None = None
        self.high_grade_override_consumed = False
        self.high_grade_last_score: float | None = None
        self.high_grade_updated_at: str | None = None
        self._load_state()

    def _load_state(self) -> None:
        if not self.state_path.exists():
            return
        try:
            state = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        self.last_candle_time = state.get("last_candle_time")
        self.last_signal_key = state.get("last_signal_key")
        self.known_deals = {int(value) for value in state.get("known_deals", [])}
        direction = state.get("high_grade_regime_direction")
        self.high_grade_regime_direction = direction if direction in {"BUY", "SELL"} else None
        self.high_grade_override_consumed = bool(state.get("high_grade_override_consumed", False))
        last_score = state.get("high_grade_last_score")
        self.high_grade_last_score = None if last_score is None else float(last_score)
        updated_at = state.get("high_grade_updated_at")
        self.high_grade_updated_at = str(updated_at) if updated_at else None

    def _save_state(self) -> None:
        write_json(self.state_path, {
            "last_candle_time": self.last_candle_time,
            "last_signal_key": self.last_signal_key,
            "known_deals": sorted(self.known_deals)[-5000:],
            "high_grade_regime_direction": self.high_grade_regime_direction,
            "high_grade_override_consumed": self.high_grade_override_consumed,
            "high_grade_last_score": self.high_grade_last_score,
            "high_grade_updated_at": self.high_grade_updated_at,
            "updated_at": now(),
        })

    def publish(self, **updates: Any) -> dict[str, Any]:
        current: dict[str, Any] = {}
        if self.status_path.exists():
            try:
                current = json.loads(self.status_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                current = {}
        current.update(updates)
        current["heartbeat_at"] = now()
        write_json(self.status_path, current)
        return current

    def _import_mt5(self) -> Any:
        if self.mt5 is not None:
            return self.mt5
        try:
            import MetaTrader5 as mt5
        except ImportError as exc:
            raise RuntimeError('Install MT5 support with: python -m pip install -e ".[mt5]"') from exc
        self.mt5 = mt5
        return mt5

    def validate_identity(self) -> tuple[Any, Any]:
        mt5 = self._import_mt5()
        account = mt5.account_info()
        terminal = mt5.terminal_info()
        if account is None or terminal is None:
            raise RuntimeError(f"MT5 account/terminal info unavailable: {mt5.last_error()}")
        if int(account.login) != self.login:
            raise RuntimeError("Execution refused: connected account changed from MT5_LOGIN.")
        if str(account.server) != self.server:
            raise RuntimeError("Execution refused: connected MT5 server changed.")
        if int(account.trade_mode) != int(getattr(mt5, "ACCOUNT_TRADE_MODE_DEMO", 0)):
            raise RuntimeError(f"Execution refused: account {account.login} is not an MT5 demo account.")
        if not bool(terminal.connected) or not bool(terminal.trade_allowed):
            raise RuntimeError("MT5 is disconnected or algorithmic trading is disabled.")
        return account, terminal

    def connect(self) -> None:
        mt5 = self._import_mt5()
        self.lock.acquire()
        if not mt5.initialize():
            raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}")
        if not mt5.login(self.login, password=self.password, server=self.server):
            raise RuntimeError(f"MT5 login failed: {mt5.last_error()}")
        account, _ = self.validate_identity()
        if not mt5.symbol_select(self.symbol, True):
            raise RuntimeError(f"Unable to select {self.symbol}: {mt5.last_error()}")
        self.initial_equity = float(account.equity)
        self.publish(connection="Online", broker_connection="Connected", runtime="running", mode="mt5-demo",
                     session_id=self.session_id, started_at=now(), symbol=self.symbol, timeframe=self.timeframe,
                     account_login=int(account.login), account_server=str(account.server), account_trade_mode="demo",
                     account_balance=float(account.balance), account_equity=float(account.equity),
                     account_profit=float(account.profit), currency=str(account.currency), iteration=0,
                     signals_seen=0, orders_sent=0, open_positions=0, pending_orders=0,
                     last_signal="HOLD", message="Connected to governed MT5 demo account.")

    def timeframe_code(self) -> int:
        value = getattr(self._import_mt5(), f"TIMEFRAME_{self.timeframe}", None)
        if value is None:
            raise RuntimeError(f"Unsupported timeframe: {self.timeframe}")
        return int(value)

    def market(self) -> MarketSnapshot:
        mt5 = self._import_mt5()
        count = max(80, self.slow_period + 20)
        rates = mt5.copy_rates_from_pos(self.symbol, self.timeframe_code(), 1, count)
        if rates is None or len(rates) < self.slow_period + 15:
            raise RuntimeError(f"Insufficient completed MT5 rates for {self.symbol}: {mt5.last_error()}")
        closes = [float(row["close"]) for row in rates]
        highs = [float(row["high"]) for row in rates]
        lows = [float(row["low"]) for row in rates]
        candle_time = int(rates[-1]["time"])
        fast = sum(closes[-self.fast_period:]) / self.fast_period
        slow = sum(closes[-self.slow_period:]) / self.slow_period
        tr = [max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1])) for i in range(1, len(closes))]
        atr = sum(tr[-14:]) / 14
        if atr <= 0:
            raise RuntimeError("ATR is non-positive; execution refused.")
        return MarketSnapshot(candle_time, fast, slow, atr, closes[-1])

    def signal(self, market: MarketSnapshot) -> dict[str, Any]:
        score = min(100.0, round(50.0 + abs(market.fast - market.slow) / market.atr * 50.0, 2))
        if market.fast > market.slow and score >= 60:
            side, decision = "BUY", "ENTER_MT5_DEMO"
        elif market.fast < market.slow and score >= 60:
            side, decision = "SELL", "ENTER_MT5_DEMO"
        else:
            side, decision = "HOLD", "SKIP"
        signal_key = f"{self.symbol}:{self.timeframe}:{market.candle_time}:{side}"
        if signal_key == self.last_signal_key:
            decision = "DUPLICATE_SKIP"
        return {"timestamp": now(), "session_id": self.session_id, "iteration": self.iteration,
                "candle_time": market.candle_time, "signal_key": signal_key, "symbol": self.symbol,
                "timeframe": self.timeframe, "signal": side, "decision": decision, "score": score,
                "fast_sma": round(market.fast, 5), "slow_sma": round(market.slow, 5),
                "atr": round(market.atr, 5), "close": round(market.close, 5), "mode": "mt5-demo",
                "reason": "completed-candle fast/slow SMA direction with ATR-normalised confidence"}

    def positions(self) -> list[Any]:
        return list(self._import_mt5().positions_get(symbol=self.symbol) or [])

    def orders(self) -> list[Any]:
        return list(self._import_mt5().orders_get(symbol=self.symbol) or [])

    def owned_exposure(self) -> tuple[list[Any], list[Any]]:
        owned_positions = [p for p in self.positions() if int(getattr(p, "magic", 0)) == self.magic]
        owned_orders = [o for o in self.orders() if int(getattr(o, "magic", 0)) == self.magic]
        return owned_positions, owned_orders

    def daily_realised_pnl(self) -> float:
        mt5 = self._import_mt5()
        start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        deals = mt5.history_deals_get(start, datetime.now(timezone.utc), group=f"*{self.symbol}*") or []
        return sum(float(getattr(d, "profit", 0.0)) + float(getattr(d, "commission", 0.0)) +
                   float(getattr(d, "swap", 0.0)) + float(getattr(d, "fee", 0.0))
                   for d in deals if int(getattr(d, "magic", 0)) == self.magic)

    def _filling_mode(self, info: Any) -> int:
        mt5 = self._import_mt5()
        reported = int(getattr(info, "filling_mode", -1))
        valid = [getattr(mt5, "ORDER_FILLING_FOK", None), getattr(mt5, "ORDER_FILLING_IOC", None), getattr(mt5, "ORDER_FILLING_RETURN", None)]
        if reported in valid:
            return reported
        for value in valid:
            if value is not None:
                return int(value)
        raise RuntimeError("No supported MT5 filling mode available.")

    def _volume(self, info: Any) -> float:
        volume = max(float(info.volume_min), min(float(info.volume_max), self.requested_lot))
        step = float(info.volume_step)
        if step > 0:
            volume = round(round(volume / step) * step, 8)
        return volume

    def _risk_cash(self, side: str, volume: float, entry: float, stop: float, info: Any) -> float:
        mt5 = self._import_mt5()
        order_type = mt5.ORDER_TYPE_BUY if side == "BUY" else mt5.ORDER_TYPE_SELL
        calculated = mt5.order_calc_profit(order_type, self.symbol, volume, entry, stop)
        if calculated is not None:
            return abs(float(calculated))
        tick_size = float(getattr(info, "trade_tick_size", 0.0) or getattr(info, "point", 0.0))
        tick_value = float(getattr(info, "trade_tick_value_loss", 0.0) or getattr(info, "trade_tick_value", 0.0))
        if tick_size <= 0 or tick_value <= 0:
            raise RuntimeError("Unable to calculate projected cash risk.")
        return abs(entry - stop) / tick_size * tick_value * volume

    def _refresh_high_grade_regime(self, side: str, signal_score: float) -> None:
        if side not in {"BUY", "SELL"}:
            return
        if self.high_grade_regime_direction != side:
            self.high_grade_regime_direction = side
            self.high_grade_override_consumed = False
        elif signal_score < self.high_grade_rearm_score:
            self.high_grade_override_consumed = False
        self.high_grade_last_score = signal_score
        self.high_grade_updated_at = now()

    def _consume_high_grade_override(self, side: str, signal_score: float) -> None:
        self.high_grade_regime_direction = side
        self.high_grade_override_consumed = True
        self.high_grade_last_score = signal_score
        self.high_grade_updated_at = now()

    def _spread_gate(self, *, side: str, atr: float, signal_score: float, spread_price: float,
                     point: float, digits: int) -> dict[str, Any]:
        spread_points = spread_price / point if point > 0 else float("inf")
        high_grade_atr_limit_points = atr * self.high_grade_max_spread_atr_fraction / point if point > 0 and atr > 0 else None
        extended_limit = min(self.high_grade_max_spread_points, high_grade_atr_limit_points) if high_grade_atr_limit_points is not None else None
        effective_limit = max(self.max_spread_points, extended_limit) if extended_limit is not None else self.max_spread_points
        self._refresh_high_grade_regime(side, signal_score)
        override_armed = not self.high_grade_one_per_regime or not self.high_grade_override_consumed
        metadata = {"spread_price": round(spread_price, digits), "spread_points": spread_points,
                    "point": point, "digits": digits, "atr": atr,
                    "spread_atr_fraction": spread_price / atr if atr > 0 else None,
                    "normal_spread_limit_points": self.max_spread_points,
                    "high_grade_score_threshold": self.high_grade_score,
                    "high_grade_hard_limit_points": self.high_grade_max_spread_points,
                    "high_grade_atr_limit_points": high_grade_atr_limit_points,
                    "effective_spread_limit_points": effective_limit,
                    "signal_score": signal_score, "signal_direction": side,
                    "override_armed": override_armed, "high_grade_override": False,
                    "spread_gate_mode": "rejected", "spread_gate_passed": False,
                    "rejection_reason": None,
                    "high_grade_regime_direction": self.high_grade_regime_direction,
                    "high_grade_override_consumed": self.high_grade_override_consumed}
        if point <= 0:
            metadata["rejection_reason"] = "invalid_symbol_point"
            raise SpreadGateRejected(metadata)
        if atr <= 0:
            metadata["rejection_reason"] = "invalid_atr"
            raise SpreadGateRejected(metadata)
        if spread_points <= self.max_spread_points:
            metadata.update({"spread_gate_mode": "normal", "spread_gate_passed": True})
            return metadata
        if signal_score < self.high_grade_score:
            metadata["rejection_reason"] = "spread_above_normal_signal_not_high_grade"
            raise SpreadGateRejected(metadata)
        if spread_points > self.high_grade_max_spread_points:
            metadata["rejection_reason"] = "spread_above_high_grade_hard_cap"
            raise SpreadGateRejected(metadata)
        if high_grade_atr_limit_points is None or spread_points > high_grade_atr_limit_points:
            metadata["rejection_reason"] = "spread_above_high_grade_atr_cap"
            raise SpreadGateRejected(metadata)
        if not override_armed:
            metadata["rejection_reason"] = "high_grade_override_consumed"
            raise SpreadGateRejected(metadata)
        metadata.update({"high_grade_override": True, "spread_gate_mode": "high_grade_override",
                         "spread_gate_passed": True})
        return metadata

    def build_request(self, side: str, atr: float, *, signal_score: float,
                      signal_key: str) -> tuple[dict[str, Any], float, dict[str, Any]]:
        mt5 = self._import_mt5()
        account, _ = self.validate_identity()
        info = mt5.symbol_info(self.symbol)
        tick = mt5.symbol_info_tick(self.symbol)
        if info is None or tick is None:
            raise RuntimeError(f"Symbol information unavailable for {self.symbol}")
        point = float(info.point)
        digits = int(info.digits)
        spread_price = float(tick.ask) - float(tick.bid)
        spread_gate = self._spread_gate(side=side, atr=atr, signal_score=signal_score,
                                        spread_price=spread_price, point=point, digits=digits)
        spread_gate["signal_key"] = signal_key
        try:
            owned_positions, owned_orders = self.owned_exposure()
            if len(owned_positions) >= self.max_positions or owned_orders:
                raise RuntimeError("Edith exposure limit reached or pending order exists.")
            buy = side == "BUY"
            price = float(tick.ask if buy else tick.bid)
            min_distance = max(float(getattr(info, "trade_stops_level", 0)), float(getattr(info, "trade_freeze_level", 0))) * point
            stop_distance = max(atr * self.stop_atr, min_distance + point)
            target_distance = max(atr * self.target_atr, min_distance + point)
            stop = price - stop_distance if buy else price + stop_distance
            target = price + target_distance if buy else price - target_distance
            volume = self._volume(info)
            risk_cash = self._risk_cash(side, volume, price, stop, info)
            equity_limit = float(account.equity) * self.max_risk_pct / 100.0
            if risk_cash > min(self.max_risk_cash, equity_limit):
                raise RuntimeError(f"Projected risk {risk_cash:.2f} exceeds cash/equity limit.")
            daily_pnl = self.daily_realised_pnl()
            if daily_pnl <= -self.max_daily_loss:
                raise RuntimeError("Daily loss limit reached.")
            drawdown_pct = max(0.0, (self.initial_equity - float(account.equity)) / self.initial_equity * 100.0) if self.initial_equity else 0.0
            if drawdown_pct >= self.max_drawdown_pct:
                raise RuntimeError("Runtime drawdown limit reached.")
            margin_level = float(getattr(account, "margin_level", 0.0) or 0.0)
            if float(getattr(account, "margin", 0.0)) > 0 and margin_level < self.min_margin_level:
                raise RuntimeError("Margin level below configured minimum.")
            request = {"action": mt5.TRADE_ACTION_DEAL, "symbol": self.symbol, "volume": volume,
                       "type": mt5.ORDER_TYPE_BUY if buy else mt5.ORDER_TYPE_SELL,
                       "price": round(price, digits), "sl": round(stop, digits), "tp": round(target, digits),
                       "deviation": self.deviation, "magic": self.magic, "comment": "Edith MT5 demo",
                       "type_time": mt5.ORDER_TIME_GTC, "type_filling": self._filling_mode(info)}
        except RuntimeError as exc:
            setattr(exc, "spread_gate", spread_gate)
            raise
        return request, risk_cash, spread_gate

    def send_order(self, side: str, atr: float, *, signal_score: float, signal_key: str) -> dict[str, Any]:
        mt5 = self._import_mt5()
        try:
            request, risk_cash, spread_gate = self.build_request(side, atr, signal_score=signal_score,
                                                                 signal_key=signal_key)
        except SpreadGateRejected as exc:
            event = {"timestamp": now(), "session_id": self.session_id, "status": "risk_rejected",
                     "rejection_category": "market_quality", "rejection_reason": exc.metadata.get("rejection_reason"),
                     "side": side, "symbol": self.symbol, "signal_score": signal_score,
                     "signal_key": signal_key, "comment": exc.metadata.get("rejection_reason")}
            event.update(exc.metadata)
            append_jsonl(self.orders_path, event)
            return event
        except RuntimeError as exc:
            event = {"timestamp": now(), "session_id": self.session_id, "status": "risk_rejected",
                     "side": side, "symbol": self.symbol, "signal_score": signal_score,
                     "signal_key": signal_key, "comment": str(exc)}
            spread_gate = getattr(exc, "spread_gate", None)
            if isinstance(spread_gate, dict):
                event.update(spread_gate)
            append_jsonl(self.orders_path, event)
            return event
        check = mt5.order_check(request)
        if check is None or int(check.retcode) != 0:
            event = {"timestamp": now(), "session_id": self.session_id, "status": "rejected_check",
                     "side": side, "symbol": self.symbol, "request": request,
                     "signal_score": signal_score, "signal_key": signal_key,
                     "retcode": None if check is None else int(check.retcode),
                     "comment": None if check is None else str(check.comment), "last_error": mt5.last_error()}
            event.update(spread_gate)
            append_jsonl(self.orders_path, event)
            return event
        result = mt5.order_send(request)
        ok_codes = {mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_PLACED, mt5.TRADE_RETCODE_DONE_PARTIAL}
        event = {"timestamp": now(), "session_id": self.session_id,
                 "status": "accepted" if result is not None and int(result.retcode) in ok_codes else "rejected_send",
                 "side": side, "symbol": self.symbol, "volume": request["volume"], "price": request["price"],
                 "sl": request["sl"], "tp": request["tp"], "projected_risk_cash": round(risk_cash, 2),
                 "signal_score": signal_score, "signal_key": signal_key,
                 "order": None if result is None else int(result.order), "deal": None if result is None else int(result.deal),
                 "retcode": None if result is None else int(result.retcode),
                 "comment": None if result is None else str(result.comment), "last_error": mt5.last_error()}
        event.update(spread_gate)
        append_jsonl(self.orders_path, event)
        if event["status"] == "accepted":
            self.orders_sent += 1
            if spread_gate.get("high_grade_override"):
                self._consume_high_grade_override(side, signal_score)
                self._save_state()
        return event

    def record_deals(self) -> int:
        mt5 = self._import_mt5()
        deals = mt5.history_deals_get(self.started_at, datetime.now(timezone.utc), group=f"*{self.symbol}*") or []
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
        if added:
            self._save_state()
        return added

    def step(self) -> dict[str, Any]:
        account, terminal = self.validate_identity()
        market = self.market()
        if self.last_candle_time == market.candle_time:
            return self.publish(connection="Online", broker_connection="Connected", runtime="running",
                                iteration=self.iteration, message="Awaiting next completed candle.")
        self.last_candle_time = market.candle_time
        self.iteration += 1
        signal = self.signal(market)
        append_jsonl(self.signals_path, signal)
        self.signals_seen += 1
        order = None
        if signal["decision"] == "ENTER_MT5_DEMO":
            order = self.send_order(signal["signal"], market.atr,
                                    signal_score=float(signal["score"]), signal_key=str(signal["signal_key"]))
            if order.get("status") == "accepted":
                self.last_signal_key = signal["signal_key"]
        self._save_state()
        new_deals = self.record_deals()
        positions = self.positions()
        pending = self.orders()
        return self.publish(connection="Online", broker_connection="Connected" if terminal.connected else "Disconnected",
            runtime="running", mode="mt5-demo", session_id=self.session_id, symbol=self.symbol,
            timeframe=self.timeframe, account_login=int(account.login), account_server=str(account.server),
            account_trade_mode="demo", account_balance=float(account.balance), account_equity=float(account.equity),
            account_profit=float(account.profit), currency=str(account.currency), iteration=self.iteration,
            signals_seen=self.signals_seen, orders_sent=self.orders_sent, open_positions=len(positions),
            pending_orders=len(pending), last_signal=signal["signal"], last_score=signal["score"],
            last_candle_time=market.candle_time, last_order_status=None if order is None else order["status"],
            last_spread_points=None if order is None else order.get("spread_points"),
            last_normal_spread_limit_points=None if order is None else order.get("normal_spread_limit_points"),
            last_effective_spread_limit_points=None if order is None else order.get("effective_spread_limit_points"),
            last_spread_atr_fraction=None if order is None else order.get("spread_atr_fraction"),
            last_spread_gate_mode=None if order is None else order.get("spread_gate_mode"),
            last_high_grade_override=None if order is None else order.get("high_grade_override"),
            last_rejection_category=None if order is None else order.get("rejection_category"),
            last_rejection_reason=None if order is None else order.get("rejection_reason"),
            high_grade_regime_direction=self.high_grade_regime_direction,
            high_grade_override_consumed=self.high_grade_override_consumed,
            high_grade_last_score=self.high_grade_last_score,
            daily_realised_pnl=round(self.daily_realised_pnl(), 2), new_deals=new_deals,
            message="Governed MT5 demo telemetry received.")

    def run(self) -> None:
        try:
            self.connect()
            print(f"Edith connected to governed MT5 demo account {self.login}.")
            while self.max_iterations <= 0 or self.iteration < self.max_iterations:
                status = self.step()
                print(f"[{status['heartbeat_at']}] iteration={self.iteration} signal={status.get('last_signal', '—')} orders={self.orders_sent} positions={status.get('open_positions', 0)}")
                # Pulse the heartbeat every 10 s so the dashboard never goes stale during the poll gap.
                elapsed = 0
                while elapsed < self.poll_seconds:
                    chunk = min(10, self.poll_seconds - elapsed)
                    time.sleep(chunk)
                    elapsed += chunk
                    if elapsed < self.poll_seconds:
                        self.publish(message=status.get("message", "Awaiting next completed candle."))
        except KeyboardInterrupt:
            self.publish(connection="Offline", broker_connection="Disconnected", runtime="stopped", mode="mt5-demo",
                         session_id=self.session_id, stopped_at=now(), message="MT5 demo loop stopped by operator.")
            print("Edith MT5 demo loop stopped cleanly.")
        except Exception as exc:
            self.publish(connection="Error", broker_connection="Error", runtime="failed", mode="mt5-demo",
                         session_id=self.session_id, error=repr(exc), message="MT5 demo loop failed closed.")
            raise
        finally:
            if self.mt5 is not None:
                try:
                    mt5_instance: Any = self.mt5
                    shutdown = getattr(mt5_instance, "shutdown", None)
                    if callable(shutdown):
                        shutdown()
                finally:
                    self.lock.release()


def run_from_environment() -> None:
    MT5DemoRuntime().run()
