from __future__ import annotations

from dataclasses import dataclass
from datetime import timezone
from statistics import fmean
from typing import Sequence
from uuid import NAMESPACE_URL, uuid5

from .engines import (
    Candle,
    LiquidityIntelligenceEngine,
    MarketStateEngine,
    SessionIntelligenceEngine,
    TrendStateEngine,
)
from .models import Observation, Outcome, TraceMetadata
from .persistence import ObservationStore
from .regimes import MarketRegimeClassifier, RegimeAssessment


@dataclass(frozen=True)
class ActivationContext:
    instrument: str
    timeframe: str
    liquidity_level: float
    liquidity_type: str
    liquidity_location: str
    structure_state: str
    source_key: str
    internal_external: str = "external"
    vwap_distance_sigma: float | None = None
    higher_timeframe_alignment: float | None = None


@dataclass(frozen=True)
class ActivationResult:
    observation: Observation
    regime: RegimeAssessment
    persisted: bool


class ObservationActivationService:
    """Turns candle/context inputs into append-only institutional observations.

    This service has no dependency on broker, signal, risk, or order modules.
    Reprocessing the same source key produces the same record ID and therefore
    cannot silently duplicate evidence in the append-only store.
    """

    def __init__(self, store: ObservationStore) -> None:
        self.store = store
        self.sessions = SessionIntelligenceEngine()
        self.liquidity = LiquidityIntelligenceEngine()
        self.trends = TrendStateEngine()
        self.market_states = MarketStateEngine()
        self.regimes = MarketRegimeClassifier()

    def activate(
        self,
        candles: Sequence[Candle],
        context: ActivationContext,
        *,
        outcome: Outcome | None = None,
        confidence: float = 0.0,
    ) -> ActivationResult:
        if len(candles) < 21:
            raise ValueError("at least 21 candles are required for activation")
        ordered = sorted(candles, key=lambda candle: candle.timestamp_utc)
        latest = ordered[-1]
        atr = fmean(candle.range for candle in ordered[-14:])
        ranges = [candle.range for candle in ordered[-100:]]
        volatility_percentile = sum(value <= ranges[-1] for value in ranges) / len(ranges)
        closes = [candle.close for candle in ordered]
        absolute_moves = [abs(b - a) for a, b in zip(closes[-11:-1], closes[-10:])]
        directional_move = abs(closes[-1] - closes[-10])
        total_move = sum(absolute_moves) or 1e-12
        momentum = min(directional_move / total_move, 1.0)
        recent_range = max(candle.high for candle in ordered[-10:]) - min(candle.low for candle in ordered[-10:])
        reference_range = max(candle.high for candle in ordered[-20:]) - min(candle.low for candle in ordered[-20:])
        compression = min(max(1.0 - (recent_range / max(reference_range, 1e-12)), 0.0), 1.0)

        session = self.sessions.evaluate(ordered)
        liquidity = self.liquidity.evaluate(
            ordered,
            level=context.liquidity_level,
            liquidity_type=context.liquidity_type,
            location=context.liquidity_location,
            atr=atr,
            internal_external=context.internal_external,
        )
        trend = self.trends.evaluate(ordered)
        state = self.market_states.build(
            session=session,
            liquidity=liquidity,
            trend=trend,
            atr=atr,
            volatility_percentile=volatility_percentile,
            momentum_score=momentum,
            compression_score=compression,
            structure_state=context.structure_state,
            vwap_distance_sigma=context.vwap_distance_sigma,
            higher_timeframe_alignment=context.higher_timeframe_alignment,
        )
        regime = self.regimes.classify(state)
        state.feature_values.update if False else None  # frozen mapping remains authoritative
        record_id = str(uuid5(NAMESPACE_URL, f"edith:{context.source_key}"))
        observation = Observation(
            timestamp_utc=latest.timestamp_utc.astimezone(timezone.utc),
            instrument=context.instrument,
            timeframe=context.timeframe,
            market_state=state,
            outcome=outcome or Outcome(),
            confidence=confidence,
            metadata=TraceMetadata(dataset_id="edith-activated-observations-v1"),
            record_id=record_id,
        )
        try:
            self.store.append(observation)
            persisted = True
        except Exception as exc:
            # SQLite primary-key rejection is the expected idempotency mechanism.
            if "UNIQUE constraint failed" not in str(exc):
                raise
            persisted = False
        return ActivationResult(observation=observation, regime=regime, persisted=persisted)
