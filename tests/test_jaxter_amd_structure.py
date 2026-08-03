from __future__ import annotations

import inspect
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


def signal(*, bos_time: str = "2026-01-05T00:00:00+00:00") -> AMDStructureSignal:
    return AMDStructureSignal(
        signal_id="signal-1", session_date="2026-01-05", symbol="XAUUSD", timeframe="M5",
        direction=Direction.BULLISH, asian_high=101.0, asian_low=99.0, sweep_price=98.5,
        sweep_time="2026-01-05T07:00:00+00:00", choch_time="2026-01-05T07:10:00+00:00",
        bos_time=bos_time, entry_zone=EntryZone(99.9, 100.1, 99.8, 100.2, 99.9, 100.1),
        entry_price=100.0, stop_price=99.8, target_price=100.2, target_r=1.0,
        quality_score=80.0, reasons=("test",), strategy_version="jaxter-amd-structure-v1",
    )


def test_configuration_enforces_half_to_one_percent_research_risk() -> None:
    with pytest.raises(ValueError):
        AMDStructureConfig(risk_fraction=0.02)
    with pytest.raises(ValueError):
        AMDStructureConfig(risk_fraction=0.004)
    assert AMDStructureConfig(risk_fraction=0.005).risk_fraction == 0.005
    assert AMDStructureConfig(risk_fraction=0.01).risk_fraction == 0.01


def test_engine_rejects_incomplete_candle_contract() -> None:
    with pytest.raises(ValueError, match="Missing candle columns"):
        AMDStructureEngine().scan(pd.DataFrame({"timestamp": []}))


def test_flat_session_produces_no_amd_signal() -> None:
    frame = candles([(100.0, 100.2, 99.8, 100.0)] * 200)
    assert AMDStructureEngine().scan(frame) == []


def test_backtester_is_conservative_when_stop_and_target_touch_same_bar() -> None:
    frame = candles([(100.0, 100.3, 99.7, 100.0)] * 20)
    trade = AMDStructureBacktester().evaluate(frame, [signal()])[0]
    assert trade.outcome is Outcome.LOSS
    assert trade.realised_r == -1.0


def test_entry_cannot_fill_on_bos_confirmation_candle() -> None:
    frame = candles([
        (100.0, 100.1, 99.9, 100.0),
        (100.0, 100.3, 99.7, 100.2),  # BOS candle touches the entry and would win.
        (100.3, 100.5, 100.25, 100.4),  # Never retraces after confirmation.
    ])
    trade = AMDStructureBacktester().evaluate(
        frame,
        [signal(bos_time="2026-01-05T00:05:00+00:00")],
    )[0]
    assert trade.outcome is Outcome.NO_FILL
    assert trade.entry_time is None


def test_research_runner_accepts_only_three_to_six_month_windows() -> None:
    frame = candles([(100.0, 100.2, 99.8, 100.0)] * 200)
    with pytest.raises(ValueError, match="between 3 and 6"):
        JaxterResearchRunner().run(frame, lookback_months=2)


def test_persistence_preserves_immutable_run_directory(tmp_path) -> None:
    frame = candles([(100.0, 100.2, 99.8, 100.0)] * 200)
    runner = JaxterResearchRunner()
    trades, report = runner.run(frame, lookback_months=3, source_name="fixture.csv")
    run_directory = runner.persist(trades, report, tmp_path)
    assert (run_directory / "report.json").exists()
    assert (run_directory / "trades.jsonl").exists()
    assert (tmp_path / "amd_structure_report.json").exists()
    with pytest.raises(FileExistsError):
        runner.persist(trades, report, tmp_path)


def test_empty_evidence_summary_uses_unknown_not_false_zero() -> None:
    frame = candles([(100.0, 100.2, 99.8, 100.0)] * 200)
    _, report = JaxterResearchRunner().run(frame, lookback_months=3)
    assert report["summary"]["resolved"] == 0
    assert report["summary"]["win_rate"] is None
    assert report["summary"]["expectancy_r"] is None


def test_jaxter_package_has_no_edith_or_broker_dependency() -> None:
    import lilith.jaxter.backtest as backtest
    import lilith.jaxter.engine as engine
    import lilith.jaxter.research as research

    source = "\n".join(inspect.getsource(module) for module in (engine, backtest, research))
    forbidden = ("mt5_demo", "reconciled_runtime", "MetaTrader5", "order_send", "dashboard")
    assert not [name for name in forbidden if name in source]
