from __future__ import annotations

from types import SimpleNamespace

import pytest

from lilith.mt5_demo import MT5DemoRuntime, MarketSnapshot


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
    def history_deals_get(self, *_args, **_kwargs): return ()
    def order_calc_profit(self, _type, _symbol, volume, entry, stop): return -abs(entry - stop) * volume
    def order_check(self, _request): return SimpleNamespace(retcode=0, comment="ok")
    def order_send(self, request):
        self.sent.append(request)
        return SimpleNamespace(retcode=self.TRADE_RETCODE_DONE, order=11, deal=12, comment="done")


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
        "EDITH_MT5_MAX_SPREAD_POINTS": "30",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)


def runtime(tmp_path, fake=None):
    return MT5DemoRuntime(mt5=fake or FakeMT5(), data_dir=tmp_path)


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


def test_broker_reported_filling_mode_is_used(tmp_path):
    fake = FakeMT5()
    instance = runtime(tmp_path, fake)
    instance.initial_equity = 100.0
    request, _ = instance.build_request("BUY", atr=1.0)
    assert request["type_filling"] == fake.ORDER_FILLING_FOK


def test_wide_spread_is_rejected(tmp_path):
    fake = FakeMT5()
    fake.tick.ask = 2001.0
    fake.tick.bid = 2000.0
    instance = runtime(tmp_path, fake)
    instance.initial_equity = 100.0
    with pytest.raises(RuntimeError, match="Spread"):
        instance.build_request("BUY", atr=1.0)


def test_pending_order_blocks_new_order(tmp_path):
    fake = FakeMT5()
    fake._orders = [SimpleNamespace(magic=260729)]
    instance = runtime(tmp_path, fake)
    instance.initial_equity = 100.0
    with pytest.raises(RuntimeError, match="pending order"):
        instance.build_request("BUY", atr=1.0)


def test_risk_limit_rejects_order(tmp_path, monkeypatch):
    monkeypatch.setenv("EDITH_MT5_MAX_RISK_CASH", "0.01")
    fake = FakeMT5()
    instance = runtime(tmp_path, fake)
    instance.initial_equity = 100.0
    event = instance.send_order("BUY", atr=10.0)
    assert event["status"] == "risk_rejected"
    assert fake.sent == []


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
