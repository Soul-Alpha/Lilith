from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from lilith.intelligence import (
    Candle,
    EvidencePolicy,
    EvidenceStage,
    LiquidityIntelligenceEngine,
    MarketStateEngine,
    Observation,
    ObservationStore,
    OlympusCompatibilityAdapter,
    Outcome,
    PatternDNAEngine,
    SessionIntelligenceEngine,
    TrendStateEngine,
)


def candles(count: int = 30) -> list[Candle]:
    start = datetime(2026, 7, 30, 7, 0, tzinfo=timezone.utc)
    result = []
    price = 3300.0
    for index in range(count):
        close = price + 0.4
        result.append(Candle(start + timedelta(minutes=5 * index), price, close + 0.2, price - 0.2, close, 100 + index))
        price = close
    return result


def market_state():
    series = candles()
    session = SessionIntelligenceEngine().evaluate(series)
    trend = TrendStateEngine().evaluate(series)
    liquidity = LiquidityIntelligenceEngine().evaluate(
        series[:-1] + [replace(series[-1], high=series[-1].close + 2.0, close=series[-1].close - 0.5)],
        level=series[-1].close,
        liquidity_type="session_high",
        location="london_high",
        atr=1.0,
    )
    return MarketStateEngine().build(
        session=session,
        liquidity=liquidity,
        trend=trend,
        atr=1.0,
        volatility_percentile=0.7,
        momentum_score=0.8,
        compression_score=0.2,
        structure_state="bullish_continuation",
    )


def observation(index: int, r_multiple: float) -> Observation:
    return Observation(
        timestamp_utc=datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc) + timedelta(minutes=index),
        instrument="XAUUSDm",
        timeframe="5m",
        market_state=market_state(),
        outcome=Outcome(status="closed", r_multiple=r_multiple, pnl=r_multiple * 10),
        confidence=0.75,
    )


def test_observation_store_is_append_only(tmp_path):
    store = ObservationStore(tmp_path / "observations.sqlite3")
    item = observation(1, 1.5)
    store.append(item)
    assert store.count() == 1
    assert store.records(instrument="XAUUSDm")[0]["record_id"] == item.record_id
    with pytest.raises(Exception):
        store.append(item)
    assert store.count() == 1


def test_engines_create_bounded_observational_state():
    state = market_state()
    assert state.session.opening_range > 0
    assert state.trend.direction == "bullish"
    assert 0 <= state.trend.strength <= 1
    assert state.liquidity.swept is True
    assert len(state.fingerprint()) == 64


def test_pattern_dna_promotes_positive_stable_evidence():
    policy = EvidencePolicy(candidate_sample=3, validated_sample=5, trusted_sample=8)
    items = [observation(index, 1.0 if index % 4 else -0.25) for index in range(8)]
    pattern = PatternDNAEngine(policy).discover(items)[0]
    assert pattern.sample_size == 8
    assert pattern.expectancy_r > 0
    assert pattern.evidence_stage == EvidenceStage.TRUSTED
    assert 0 <= pattern.confidence_low <= pattern.confidence_high <= 1


def test_negative_pattern_is_retired_after_validation_sample():
    policy = EvidencePolicy(candidate_sample=2, validated_sample=4, trusted_sample=8)
    items = [observation(index, -0.5) for index in range(4)]
    assert PatternDNAEngine(policy).discover(items)[0].evidence_stage == EvidenceStage.RETIRED


def test_olympus_adapter_is_transport_only():
    item = observation(1, 1.0)
    exported = OlympusCompatibilityAdapter.export_observation(item)
    assert exported["source_system"] == "edith"
    assert exported["strategy_version"] == "unchanged"
    assert exported["record_id"] == item.record_id
    assert "approval" not in exported
    assert "gate" not in exported


def test_naive_datetimes_are_rejected():
    with pytest.raises(ValueError, match="timezone-aware"):
        Observation(
            timestamp_utc=datetime(2026, 7, 30),
            instrument="XAUUSDm",
            timeframe="5m",
            market_state=market_state(),
        )
