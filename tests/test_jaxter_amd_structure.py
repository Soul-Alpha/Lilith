from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from lilith.jaxter import (
    AMDStructureBacktester,
    AMDStructureConfig,
    AMDStructureEngine,
    AMDStructureSignal,
    Direction,
    EntryZone,
    JaxterResearchRunner,
    Outcome,
)


def candles(rows: list[tuple[float, float, float, float]]) -> pd.DataFrame:
    start = datetime(2026, 1, 5, tzinfo=timezone.utc)
    return pd.DataFrame([
        {"timestamp": start + timedelta(minutes=5 * index), "open": o, "high": h, "low": l, "close": c}
        for index, (o, h, l, c) in enumerate(rows)
    ])


def test_configuration_caps_research_risk_at_one_percent() -> None:
    with pytest.raises(ValueError):
        AMDStructureConfig(risk_fraction=0.02)
    assert AMDStructureConfig(risk_fraction=0.005).risk_fraction == 0.005


def test_engine_rejects_incomplete_candle_contract() -> None:
    with pytest.raises(ValueError, match="Missing candle columns"):
        AMDStructureEngine().scan(pd.DataFrame({"timestamp": []}))


def test_flat_session_produces_no_amd_signal() -> None:
    frame = candles([(100.0, 100.2, 99.8, 100.0)] * 200)
    assert AMDStructureEngine().scan(frame) == []


def test_backtester_is_conservative_when_stop_and_target_touch_same_bar() -> None:
    frame = candles([(100.0, 100.3, 99.7, 100.0)] * 20)
    signal = AMDStructureSignal(
        signal_id="signal-1", session_date="2026-01-05", symbol="XAUUSD", timeframe="M5",
        direction=Direction.BULLISH, asian_high=101.0, asian_low=99.0, sweep_price=98.5,
        sweep_time="2026-01-05T07:00:00+00:00", choch_time="2026-01-05T07:10:00+00:00",
        bos_time="2026-01-05T00:00:00+00:00", entry_zone=EntryZone(99.9, 100.1, 99.8, 100.2, 99.9, 100.1),
        entry_price=100.0, stop_price=99.8, target_price=100.2, target_r=1.0,
        quality_score=80.0, reasons=("test",), strategy_version="jaxter-amd-structure-v1",
    )
    trade = AMDStructureBacktester().evaluate(frame, [signal])[0]
    assert trade.outcome is Outcome.LOSS
    assert trade.realised_r == -1.0


def test_research_runner_accepts_only_three_to_six_month_windows() -> None:
    frame = candles([(100.0, 100.2, 99.8, 100.0)] * 200)
    with pytest.raises(ValueError, match="between 3 and 6"):
        JaxterResearchRunner().run(frame, lookback_months=2)


def test_jaxter_package_has_no_edith_runtime_dependency() -> None:
    import lilith.jaxter.backtest as backtest
    import lilith.jaxter.engine as engine
    import lilith.jaxter.research as research

    sources = " ".join((engine.__file__ or "", backtest.__file__ or "", research.__file__ or ""))
    assert "mt5_demo" not in sources
    assert "reconciled_runtime" not in sources
