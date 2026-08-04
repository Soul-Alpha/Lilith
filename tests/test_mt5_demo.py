from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from lilith.mt5_demo import MT5DemoRuntime, MarketSnapshot
from lilith.mt5_demo import SpreadGateRejected


class FakeMT5:
    ACCOUNT_TRADE_MODE_DEMO = 0
    TIMEFRAME_M5 = 5
    TRADE_ACTION_DEAL = 1
    ORDER_TYPE_BUY = 0
    ORDER_TYPE_SELL = 1
    ORDER_TIME_GTC = 0
    ORDER_FILLING_FOK = 0
    ORDER_FILLING_IOC = 1
    ORDER_FILLING_RETURN = 2
    TRADE_RETCODE_DONE = 10009
    TRADE_RETCODE_PLACED = 10008
    TRADE_RETCODE_DONE_PARTIAL = 10010

    def __init__(self) -> None:
        self.account = SimpleNamespace(
            login=123456,
            server="Broker-Demo",
            trade_mode=0,
            balance=100.0,
            equity=100.0,
            profit=0.0,
            currency="USD",
            margin=0.0,
            margin_level=0.0,
        )
        self.terminal = SimpleNamespace(connected=True, trade_allowed=True)
        self.info = SimpleNamespace(
            volume_min=0.01,
            volume_max=100.0,
            volume_step=0.01,
            digits=2,
            point=0.01,
            trade_stops_level=10,
            trade_freeze_level=0,
            filling_mode=self.ORDER_FILLING_FOK,
            trade_tick_size=0.01,
            trade_tick_value_loss=0.01,
            trade_tick_value=0.01,
        )
        self.tick = SimpleNamespace(ask=2000.20, bid=2000.00)
        self.sent: list[dict] = []
        self._positions: list[SimpleNamespace] = []
        self._orders: list[SimpleNamespace] = []
        self._deals: list[SimpleNamespace] = []
        self.check_retcode = 0
        self.send_retcode = self.TRADE_RETCODE_DONE

    def initialize(self): return True
    def login(self, *_args, **_kwargs): return True
    def shutdown(self): return None
    def last_error(self): return (0, "ok")
    def account_info(self): return self.account
    def terminal_info(self): return self.terminal
    def symbol_select(self, *_args): return True
    def symbol_info(self, *_args): return self.info
    def symbol_info_tick(self, *_args): return self.tick
    def positions_get(self, **_kwargs): return tuple(self._positions)
    def orders_get(self, **_kwargs): return tuple(self._orders)
    def history_deals_get(self, *_args, **_kwargs): return tuple(self._deals)
    def order_calc_profit(self, _type, _symbol, volume, entry, stop): return -abs(entry - stop) * volume
    def order_check(self, _request): return SimpleNamespace(retcode=self.check_retcode, comment="ok")
    def order_send(self, request):
        self.sent.append(request)
        return SimpleNamespace(retcode=self.send_retcode, order=11, deal=12, comment="done")


@pytest.fixture(autouse=True)
def configured_environment(monkeypatch):
    values = {
        "LILITH_EXECUTION_MODE": "mt5-demo",
        "EDITH_MT5_CONFIRM_DEMO": "YES",
        "MT5_LOGIN": "123456",
        "MT5_PASSWORD": "secret",
        "MT5_SERVER": "Broker-Demo",
        "EDITH_MT5_MAX_RISK_CASH": "5",
        "EDITH_MT5_MAX_RISK_PCT": "5",
        "EDITH_MT5_MAX_SPREAD_POINTS": "80",
        "EDITH_MT5_HIGH_GRADE_SCORE": "85",
        "EDITH_MT5_HIGH_GRADE_MAX_SPREAD_POINTS": "260",
        "EDITH_MT5_HIGH_GRADE_MAX_SPREAD_ATR_FRACTION": "0.07",
        "EDITH_MT5_HIGH_GRADE_REARM_SCORE": "70",
        "EDITH_MT5_HIGH_GRADE_ONE_PER_REGIME": "YES",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)


def runtime(tmp_path, fake=None):
    return MT5DemoRuntime(mt5=fake or FakeMT5(), data_dir=tmp_path)


def set_spread_points(fake: FakeMT5, points: float) -> None:
    fake.tick.bid = 2000.00
    fake.tick.ask = fake.tick.bid + points * fake.info.point


def signal_kwargs(score: float = 90.0, key: str = "XAUUSDm:M5:100:BUY") -> dict[str, object]:
    return {"signal_score": score, "signal_key": key}


def test_refuses_non_demo_account(tmp_path):
    fake = FakeMT5()
    fake.account.trade_mode = 2
    with pytest.raises(RuntimeError, match="not an MT5 demo account"):
        runtime(tmp_path, fake).validate_identity()


def test_refuses_changed_login_during_runtime(tmp_path):
    fake = FakeMT5()
    instance = runtime(tmp_path, fake)
    fake.account.login = 999999
    with pytest.raises(RuntimeError, match="connected account changed"):
        instance.validate_identity()


def test_refuses_changed_server(tmp_path):
    fake = FakeMT5()
    instance = runtime(tmp_path, fake)
    fake.account.server = "Broker-Live"
    with pytest.raises(RuntimeError, match="server changed"):
        instance.validate_identity()


def test_duplicate_signal_is_not_reentered(tmp_path):
    instance = runtime(tmp_path)
    market = MarketSnapshot(100, 11.0, 10.0, 1.0, 10.5)
    first = instance.signal(market)
    instance.last_signal_key = first["signal_key"]
    second = instance.signal(market)
    assert first["decision"] == "ENTER_MT5_DEMO"
    assert second["decision"] == "DUPLICATE_SKIP"


def test_enter_mt5_demo_decision_attempts_order(tmp_path):
    fake = FakeMT5()
    instance = runtime(tmp_path, fake)
    instance.market = lambda: MarketSnapshot(100, 11.0, 10.0, 1.0, 10.5)  # type: ignore[method-assign]

    status = instance.step()

    assert len(fake.sent) == 1
    assert fake.sent[0]["type"] == fake.ORDER_TYPE_BUY
    assert status["last_signal"] == "BUY"
    assert status["last_order_status"] == "accepted"
    assert instance.orders_sent == 1


def test_broker_reported_filling_mode_is_used(tmp_path):
    fake = FakeMT5()
    instance = runtime(tmp_path, fake)
    instance.initial_equity = 100.0
    request, _, spread_gate = instance.build_request("BUY", atr=1.0, **signal_kwargs())
    assert request["type_filling"] == fake.ORDER_FILLING_FOK
    assert spread_gate["spread_gate_mode"] == "normal"


def test_wide_spread_is_rejected(tmp_path):
    fake = FakeMT5()
    set_spread_points(fake, 270)
    instance = runtime(tmp_path, fake)
    instance.initial_equity = 100.0
    with pytest.raises(SpreadGateRejected) as exc:
        instance.build_request("BUY", atr=100.0, **signal_kwargs(score=95.0))
    assert exc.value.metadata["rejection_reason"] == "spread_above_high_grade_hard_cap"


def test_pending_order_blocks_new_order(tmp_path):
    fake = FakeMT5()
    fake._orders = [SimpleNamespace(magic=260729)]
    instance = runtime(tmp_path, fake)
    instance.initial_equity = 100.0
    with pytest.raises(RuntimeError, match="pending order"):
        instance.build_request("BUY", atr=1.0, **signal_kwargs())


def test_risk_limit_rejects_order(tmp_path, monkeypatch):
    monkeypatch.setenv("EDITH_MT5_MAX_RISK_CASH", "0.01")
    fake = FakeMT5()
    instance = runtime(tmp_path, fake)
    instance.initial_equity = 100.0
    event = instance.send_order("BUY", atr=10.0, **signal_kwargs())
    assert event["status"] == "risk_rejected"
    assert fake.sent == []


def test_normal_signal_within_normal_spread_passes_without_override(tmp_path):
    fake = FakeMT5()
    set_spread_points(fake, 70)
    instance = runtime(tmp_path, fake)
    instance.initial_equity = 100.0

    event = instance.send_order("BUY", atr=100.0, **signal_kwargs(score=70.0))

    assert event["status"] == "accepted"
    assert event["spread_gate_mode"] == "normal"
    assert event["high_grade_override"] is False


def test_high_grade_signal_within_normal_spread_does_not_consume_override(tmp_path):
    fake = FakeMT5()
    set_spread_points(fake, 70)
    instance = runtime(tmp_path, fake)
    instance.initial_equity = 100.0

    event = instance.send_order("BUY", atr=100.0, **signal_kwargs(score=90.0))

    assert event["status"] == "accepted"
    assert event["spread_gate_mode"] == "normal"
    assert event["high_grade_override"] is False
    assert instance.high_grade_override_consumed is False


def test_score_below_high_grade_threshold_rejects_extended_spread(tmp_path):
    fake = FakeMT5()
    set_spread_points(fake, 240)
    instance = runtime(tmp_path, fake)
    instance.initial_equity = 100.0

    event = instance.send_order("BUY", atr=100.0, **signal_kwargs(score=84.99))

    assert event["status"] == "risk_rejected"
    assert event["rejection_category"] == "market_quality"
    assert event["rejection_reason"] == "spread_above_normal_signal_not_high_grade"


def test_score_exactly_high_grade_threshold_allows_extended_spread(tmp_path):
    fake = FakeMT5()
    set_spread_points(fake, 240)
    instance = runtime(tmp_path, fake)
    instance.initial_equity = 100.0

    event = instance.send_order("BUY", atr=100.0, **signal_kwargs(score=85.0))

    assert event["status"] == "accepted"
    assert event["spread_gate_mode"] == "high_grade_override"
    assert event["high_grade_override"] is True


def test_high_grade_spread_inside_hard_and_atr_caps_passes(tmp_path):
    fake = FakeMT5()
    set_spread_points(fake, 240)
    instance = runtime(tmp_path, fake)
    instance.initial_equity = 100.0

    event = instance.send_order("BUY", atr=100.0, **signal_kwargs(score=90.0))

    assert event["status"] == "accepted"
    assert event["effective_spread_limit_points"] == 260.0


def test_high_grade_spread_above_hard_cap_rejects(tmp_path):
    fake = FakeMT5()
    set_spread_points(fake, 270)
    instance = runtime(tmp_path, fake)
    instance.initial_equity = 100.0

    event = instance.send_order("BUY", atr=100.0, **signal_kwargs(score=95.0))

    assert event["status"] == "risk_rejected"
    assert event["rejection_reason"] == "spread_above_high_grade_hard_cap"


def test_high_grade_spread_below_atr_fraction_cap_passes(tmp_path):
    fake = FakeMT5()
    set_spread_points(fake, 240)
    instance = runtime(tmp_path, fake)
    instance.initial_equity = 100.0

    event = instance.send_order("BUY", atr=100.0, **signal_kwargs(score=90.0))

    assert event["status"] == "accepted"
    assert event["spread_atr_fraction"] <= 0.07


def test_high_grade_spread_above_atr_fraction_cap_rejects(tmp_path):
    fake = FakeMT5()
    set_spread_points(fake, 240)
    instance = runtime(tmp_path, fake)
    instance.initial_equity = 100.0

    event = instance.send_order("BUY", atr=20.0, **signal_kwargs(score=90.0))

    assert event["status"] == "risk_rejected"
    assert event["rejection_reason"] == "spread_above_high_grade_atr_cap"


def test_invalid_atr_fails_closed(tmp_path):
    fake = FakeMT5()
    set_spread_points(fake, 70)
    instance = runtime(tmp_path, fake)
    instance.initial_equity = 100.0

    event = instance.send_order("BUY", atr=0.0, **signal_kwargs(score=90.0))

    assert event["status"] == "risk_rejected"
    assert event["rejection_reason"] == "invalid_atr"


def test_invalid_symbol_point_fails_closed(tmp_path):
    fake = FakeMT5()
    fake.info.point = 0.0
    instance = runtime(tmp_path, fake)
    instance.initial_equity = 100.0

    event = instance.send_order("BUY", atr=100.0, **signal_kwargs(score=90.0))

    assert event["status"] == "risk_rejected"
    assert event["rejection_reason"] == "invalid_symbol_point"


def test_first_high_grade_signal_in_regime_allows_override(tmp_path):
    fake = FakeMT5()
    set_spread_points(fake, 240)
    instance = runtime(tmp_path, fake)
    instance.initial_equity = 100.0

    event = instance.send_order("BUY", atr=100.0, **signal_kwargs(score=91.0))


    assert event["status"] == "accepted"
    assert event["override_armed"] is True

def test_accepted_override_consumes_regime_allowance(tmp_path):
    fake = FakeMT5()
    set_spread_points(fake, 240)
    instance = runtime(tmp_path, fake)
    instance.initial_equity = 100.0
    first = instance.send_order("BUY", atr=100.0, **signal_kwargs(score=91.0, key="first"))

    second = instance.send_order("BUY", atr=100.0, **signal_kwargs(score=92.0, key="second"))

    assert first["status"] == "accepted"
    assert second["status"] == "risk_rejected"
    assert second["rejection_reason"] == "high_grade_override_consumed"


def test_consumed_override_does_not_block_normal_spread(tmp_path):
    fake = FakeMT5()
    set_spread_points(fake, 240)
    instance = runtime(tmp_path, fake)
    instance.initial_equity = 100.0
    instance.send_order("BUY", atr=100.0, **signal_kwargs(score=91.0, key="first"))
    set_spread_points(fake, 70)

    event = instance.send_order("BUY", atr=100.0, **signal_kwargs(score=92.0, key="second"))

    assert event["status"] == "accepted"
    assert event["spread_gate_mode"] == "normal"
    assert event["high_grade_override"] is False


def test_direction_change_rearms_override(tmp_path):
    fake = FakeMT5()
    set_spread_points(fake, 240)
    instance = runtime(tmp_path, fake)
    instance.initial_equity = 100.0
    instance.send_order("BUY", atr=100.0, **signal_kwargs(score=91.0, key="buy"))

    event = instance.send_order("SELL", atr=100.0, **signal_kwargs(score=87.0, key="sell"))

    assert event["status"] == "accepted"
    assert event["signal_direction"] == "SELL"
    assert event["high_grade_override"] is True


def test_score_below_rearm_rearms_same_direction(tmp_path):
    fake = FakeMT5()
    set_spread_points(fake, 240)
    instance = runtime(tmp_path, fake)
    instance.initial_equity = 100.0
    instance.send_order("BUY", atr=100.0, **signal_kwargs(score=91.0, key="first"))
    set_spread_points(fake, 70)
    instance.send_order("BUY", atr=100.0, **signal_kwargs(score=68.0, key="rearm"))
    set_spread_points(fake, 240)

    event = instance.send_order("BUY", atr=100.0, **signal_kwargs(score=86.0, key="second"))

    assert event["status"] == "accepted"
    assert event["high_grade_override"] is True


def test_failed_risk_gate_does_not_consume_override(tmp_path, monkeypatch):
    monkeypatch.setenv("EDITH_MT5_MAX_RISK_CASH", "0.01")
    fake = FakeMT5()
    set_spread_points(fake, 240)
    instance = runtime(tmp_path, fake)
    instance.initial_equity = 100.0

    event = instance.send_order("BUY", atr=100.0, **signal_kwargs(score=91.0))

    assert event["status"] == "risk_rejected"
    assert event["high_grade_override"] is True
    assert instance.high_grade_override_consumed is False


def test_failed_broker_check_does_not_consume_override(tmp_path):
    fake = FakeMT5()
    fake.check_retcode = 10021
    set_spread_points(fake, 240)
    instance = runtime(tmp_path, fake)
    instance.initial_equity = 100.0

    event = instance.send_order("BUY", atr=100.0, **signal_kwargs(score=91.0))

    assert event["status"] == "rejected_check"
    assert event["high_grade_override"] is True
    assert instance.high_grade_override_consumed is False


def test_failed_order_send_does_not_consume_override(tmp_path):
    fake = FakeMT5()
    fake.send_retcode = 10021
    set_spread_points(fake, 240)
    instance = runtime(tmp_path, fake)
    instance.initial_equity = 100.0

    event = instance.send_order("BUY", atr=100.0, **signal_kwargs(score=91.0))
    assert event["status"] == "rejected_send"
    assert event["high_grade_override"] is True
    assert instance.high_grade_override_consumed is False


def test_accepted_order_consumes_override(tmp_path):
    fake = FakeMT5()
    set_spread_points(fake, 240)
    instance = runtime(tmp_path, fake)
    instance.initial_equity = 100.0

    event = instance.send_order("BUY", atr=100.0, **signal_kwargs(score=91.0))
    assert event["status"] == "accepted"
    assert instance.high_grade_override_consumed is True


def test_consumed_high_grade_state_survives_restart(tmp_path):
    fake = FakeMT5()
    set_spread_points(fake, 240)
    instance = runtime(tmp_path, fake)
    instance.initial_equity = 100.0
    instance.send_order("BUY", atr=100.0, **signal_kwargs(score=91.0))

    restored = runtime(tmp_path, fake)
    restored.initial_equity = 100.0
    event = restored.send_order("BUY", atr=100.0, **signal_kwargs(score=92.0, key="after_restart"))
    assert event["status"] == "risk_rejected"
    assert event["rejection_reason"] == "high_grade_override_consumed"


def test_legacy_state_without_high_grade_fields_loads_safely(tmp_path):
    (tmp_path / "mt5_runtime_state.json").write_text(json.dumps({"last_candle_time": 777, "known_deals": [101]}), encoding="utf-8")
    instance = runtime(tmp_path)

    assert instance.last_candle_time == 777
    assert instance.known_deals == {101}
    assert instance.high_grade_regime_direction is None
    assert instance.high_grade_override_consumed is False
    assert instance.high_grade_last_score is None


def test_deal_state_is_durable(tmp_path):
    instance = runtime(tmp_path)
    instance.known_deals = {101, 102}
    instance.last_candle_time = 777
    instance.last_signal_key = "key"
    instance._save_state()
    restored = runtime(tmp_path)
    assert restored.known_deals == {101, 102}
    assert restored.last_candle_time == 777
    assert restored.last_signal_key == "key"


def test_singleton_lock_rejects_second_runtime(tmp_path):
    first = runtime(tmp_path)
    second = runtime(tmp_path)
    first.lock.acquire()
    try:
        with pytest.raises(RuntimeError, match="Another Edith runtime"):
            second.lock.acquire()
    finally:
        first.lock.release()
