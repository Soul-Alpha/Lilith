from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timezone
from math import atan, pi
from statistics import fmean
from typing import Sequence

from .models import LiquidityState, MarketStateVector, SessionName, SessionState, TrendState


@dataclass(frozen=True)
class Candle:
    timestamp_utc: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0

    def __post_init__(self) -> None:
        if self.timestamp_utc.tzinfo is None:
            raise ValueError("candle timestamp must be timezone-aware")
        if self.high < max(self.open, self.close) or self.low > min(self.open, self.close):
            raise ValueError("invalid OHLC candle")

    @property
    def range(self) -> float:
        return max(self.high - self.low, 0.0)


class SessionIntelligenceEngine:
    """UTC session classifier with deterministic opening-range evidence."""

    def classify(self, timestamp: datetime) -> tuple[SessionName, datetime]:
        timestamp = timestamp.astimezone(timezone.utc)
        day = timestamp.date()
        current = timestamp.time()
        if time(12, 0) <= current < time(16, 0):
            return SessionName.OVERLAP, datetime.combine(day, time(12, 0), timezone.utc)
        if time(7, 0) <= current < time(12, 0):
            return SessionName.LONDON, datetime.combine(day, time(7, 0), timezone.utc)
        if time(16, 0) <= current < time(21, 0):
            return SessionName.NEW_YORK, datetime.combine(day, time(12, 0), timezone.utc)
        if current >= time(22, 0):
            return SessionName.ASIA, datetime.combine(day, time(22, 0), timezone.utc)
        if current < time(7, 0):
            previous_day = timestamp.date()
            return SessionName.ASIA, datetime.combine(previous_day, time(0, 0), timezone.utc)
        return SessionName.OFF_SESSION, datetime.combine(day, time(0, 0), timezone.utc)

    def evaluate(self, candles: Sequence[Candle], opening_minutes: int = 30) -> SessionState:
        if not candles:
            raise ValueError("candles are required")
        latest = candles[-1]
        name, session_open = self.classify(latest.timestamp_utc)
        elapsed = max(int((latest.timestamp_utc - session_open).total_seconds() // 60), 0)
        relevant = [c for c in candles if c.timestamp_utc >= session_open]
        opening = [c for c in relevant if (c.timestamp_utc - session_open).total_seconds() < opening_minutes * 60]
        opening = opening or relevant[:1]
        opening_high = max(c.high for c in opening)
        opening_low = min(c.low for c in opening)
        session_high = max(c.high for c in relevant)
        session_low = min(c.low for c in relevant)
        direction = None
        velocity = 0.0
        false_breakout = False
        if latest.close > opening_high:
            direction = "up"
            velocity = (latest.close - opening_high) / max(latest.range, 1e-12)
        elif latest.close < opening_low:
            direction = "down"
            velocity = (opening_low - latest.close) / max(latest.range, 1e-12)
        else:
            false_breakout = any(c.high > opening_high or c.low < opening_low for c in relevant[len(opening):])
        return SessionState(
            name=name,
            minutes_since_open=elapsed,
            opening_range=opening_high - opening_low,
            session_range=session_high - session_low,
            breakout_direction=direction,
            breakout_velocity=max(velocity, 0.0),
            false_breakout=false_breakout,
        )


class LiquidityIntelligenceEngine:
    """Classifies a level interaction without producing a trading signal."""

    def evaluate(
        self,
        candles: Sequence[Candle],
        level: float,
        liquidity_type: str,
        location: str,
        atr: float,
        internal_external: str = "external",
    ) -> LiquidityState:
        if len(candles) < 2:
            raise ValueError("at least two candles are required")
        latest = candles[-1]
        previous = candles[-2]
        upward_sweep = latest.high > level and latest.close <= level
        downward_sweep = latest.low < level and latest.close >= level
        swept = upward_sweep or downward_sweep
        depth = 0.0
        if upward_sweep:
            depth = latest.high - level
        elif downward_sweep:
            depth = level - latest.low
        wick = (latest.high - max(latest.open, latest.close)) if upward_sweep else (min(latest.open, latest.close) - latest.low)
        rejection = wick / max(latest.range, 1e-12) if swept else 0.0
        displacement = abs(latest.close - previous.close) / max(atr, 1e-12)
        return LiquidityState(
            liquidity_type=liquidity_type,
            location=location,
            internal_external=internal_external,
            swept=swept,
            sweep_depth_atr=depth / max(atr, 1e-12),
            sweep_duration_bars=1 if swept else 0,
            recovery_speed_bars=1 if swept else None,
            rejection_strength=min(max(rejection, 0.0), 1.0),
            displacement_atr=max(displacement, 0.0),
        )


class TrendStateEngine:
    def evaluate(self, candles: Sequence[Candle], fast_period: int = 5, slow_period: int = 20) -> TrendState:
        if len(candles) < slow_period + 1:
            raise ValueError("insufficient candles for trend evaluation")
        closes = [c.close for c in candles]
        fast = fmean(closes[-fast_period:])
        slow = fmean(closes[-slow_period:])
        previous_slow = fmean(closes[-slow_period - 1:-1])
        scale = max(fmean(c.range for c in candles[-slow_period:]), 1e-12)
        separation = (fast - slow) / scale
        slope = (slow - previous_slow) / scale
        direction = "bullish" if separation > 0.05 else "bearish" if separation < -0.05 else "neutral"
        strength = min(abs(separation) / 3.0, 1.0)
        acceleration = max(min((slope - ((closes[-2] - closes[-3]) / scale)) / 3.0, 1.0), -1.0)
        maturity = min(sum(1 for a, b in zip(closes[-slow_period:], closes[-slow_period + 1:]) if (b - a) * separation > 0) / slow_period, 1.0)
        distance = abs(closes[-1] - fast) / scale
        exhaustion = min(max(distance - 1.0, 0.0) / 3.0, 1.0)
        pullback_quality = 1.0 - min(distance / 3.0, 1.0)
        angle = abs(atan(slope)) / (pi / 2)
        structure_health = min((strength + maturity + angle) / 3.0, 1.0)
        return TrendState(direction, strength, maturity, acceleration, exhaustion, pullback_quality, structure_health)


class MarketStateEngine:
    def build(
        self,
        *,
        session: SessionState,
        liquidity: LiquidityState,
        trend: TrendState,
        atr: float,
        volatility_percentile: float,
        momentum_score: float,
        compression_score: float,
        structure_state: str,
        vwap_distance_sigma: float | None = None,
        higher_timeframe_alignment: float | None = None,
    ) -> MarketStateVector:
        bounded = (volatility_percentile, momentum_score, compression_score)
        if any(not 0.0 <= value <= 1.0 for value in bounded):
            raise ValueError("percentile and scores must be between 0 and 1")
        return MarketStateVector(
            session=session,
            liquidity=liquidity,
            trend=trend,
            atr=atr,
            volatility_percentile=volatility_percentile,
            momentum_score=momentum_score,
            compression_score=compression_score,
            structure_state=structure_state,
            vwap_distance_sigma=vwap_distance_sigma,
            higher_timeframe_alignment=higher_timeframe_alignment,
            feature_values={
                "session": session.name.value,
                "sweep": liquidity.swept,
                "trend_direction": trend.direction,
                "trend_strength": trend.strength,
                "volatility_percentile": volatility_percentile,
                "momentum_score": momentum_score,
                "compression_score": compression_score,
            },
        )
