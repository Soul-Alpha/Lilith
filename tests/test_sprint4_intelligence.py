from __future__ import annotations

from datetime import datetime, timedelta, timezone

from lilith.intelligence import Candle, Observation, Outcome, ObservationStore
from lilith.intelligence.activation import ActivationContext, ObservationActivationService
from lilith.intelligence.probability import BayesianProbabilityEngine, DriftMonitor
from lilith.intelligence.regimes import MarketRegime, MarketRegimeClassifier
from lilith.intelligence.engines import MarketStateEngine
from lilith.intelligence.models import LiquidityState, SessionName, SessionState, TrendState


def candles(count: int = 30) -> list[Candle]:
    start = datetime(2026, 7, 31, 7, 0, tzinfo=timezone.utc)
    result: list[Candle] = []
    price = 3300.0
    for index in range(count):
        close = price + 0.5
        result.append(Candle(start + timedelta(minutes=5 * index), price, close + 0.2, price - 0.2, close, 100 + index))
        price = close
    return result


def state(*, volatility: float = 0.7, momentum: float = 0.8, compression: float = 0.2):
    return MarketStateEngine().build(
        session=SessionState(SessionName.LONDON, 60, 2.0, 5.0),
        liquidity=LiquidityState(),
        trend=TrendState("bullish", 0.8, 0.7, 0.1, 0.1, 0.8, 0.8),
        atr=1.0,
        volatility_percentile=volatility,
        momentum_score=momentum,
        compression_score=compression,
        structure_state="bullish_continuation",
    )


def observation(index: int, r_multiple: float, confidence: float = 0.7) -> Observation:
    return Observation(
        timestamp_utc=datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc) + timedelta(minutes=index),
        instrument="XAUUSDm",
        timeframe="5m",
        market_state=state(),
        outcome=Outcome(status="closed", r_multiple=r_multiple),
        confidence=confidence,
    )


def test_activation_is_idempotent_and_append_only(tmp_path):
    store = ObservationStore(tmp_path / "observations.sqlite3")
    service = ObservationActivationService(store)
    context = ActivationContext(
        instrument="XAUUSDm",
        timeframe="5m",
        liquidity_level=3314.5,
        liquidity_type="session_high",
        liquidity_location="london_high",
        structure_state="bullish_continuation",
        source_key="historical:XAUUSDm:5m:2026-07-31T09:25:00Z",
    )
    first = service.activate(candles(), context)
    second = service.activate(candles(), context)
    assert first.persisted is True
    assert second.persisted is False
    assert first.observation.record_id == second.observation.record_id
    assert store.count() == 1


def test_regime_classifier_identifies_trending_state():
    result = MarketRegimeClassifier().classify(state())
    assert result.regime == MarketRegime.TRENDING
    assert 0 <= result.confidence <= 1
    assert "strong_trend" in result.reasons


def test_bayesian_probability_reports_uncertainty_and_calibration():
    items = [observation(index, 1.0 if index < 7 else -1.0, 0.7) for index in range(10)]
    estimate = BayesianProbabilityEngine().estimate("pattern-1", items)
    assert estimate.sample_size == 10
    assert 0.5 < estimate.probability_of_positive_r < 0.75
    assert 0 <= estimate.confidence_low <= estimate.confidence_high <= 1
    assert estimate.brier_score is not None
    assert estimate.calibration_error is not None


def test_drift_monitor_detects_probability_and_expectancy_shift():
    baseline = [observation(index, 1.0 if index < 8 else -0.25) for index in range(10)]
    recent = [observation(index + 20, -1.0 if index < 8 else 0.25) for index in range(10)]
    assessment = DriftMonitor().assess(baseline, recent)
    assert assessment.drift_detected is True
    assert assessment.score >= 1.0
    assert "positive_outcome_probability_shift" in assessment.reasons
    assert "expectancy_shift" in assessment.reasons
