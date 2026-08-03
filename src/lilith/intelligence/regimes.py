from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

try:
    from enum import StrEnum
except ImportError:  # Python < 3.11
    class StrEnum(str, Enum):
        pass

from .models import MarketStateVector


class MarketRegime(StrEnum):
    TRENDING = "trending"
    RANGING = "ranging"
    EXPANSION = "expansion"
    COMPRESSION = "compression"
    TRANSITION = "transition"
    VOLATILE = "volatile"
    QUIET = "quiet"


@dataclass(frozen=True)
class RegimeAssessment:
    regime: MarketRegime
    confidence: float
    reasons: tuple[str, ...]


class MarketRegimeClassifier:
    """Deterministic, analytics-only regime classification.

    The classifier describes the supplied market state. It does not produce a
    signal, execution approval, position size, or strategy mutation.
    """

    def classify(self, state: MarketStateVector) -> RegimeAssessment:
        trend = state.trend
        volatility = state.volatility_percentile
        compression = state.compression_score
        momentum = state.momentum_score
        reasons: list[str] = []

        if compression >= 0.72 and volatility <= 0.55:
            confidence = (compression + (1.0 - volatility)) / 2.0
            reasons.extend(("high_compression", "contained_volatility"))
            return RegimeAssessment(MarketRegime.COMPRESSION, min(confidence, 1.0), tuple(reasons))

        if volatility >= 0.82 and momentum >= 0.62:
            confidence = (volatility + momentum) / 2.0
            reasons.extend(("extreme_volatility", "strong_momentum"))
            return RegimeAssessment(MarketRegime.EXPANSION, min(confidence, 1.0), tuple(reasons))

        if volatility >= 0.85:
            reasons.append("extreme_volatility")
            return RegimeAssessment(MarketRegime.VOLATILE, volatility, tuple(reasons))

        if trend.strength >= 0.62 and trend.structure_health >= 0.55:
            confidence = (trend.strength + trend.structure_health + momentum) / 3.0
            reasons.extend(("strong_trend", "healthy_structure"))
            return RegimeAssessment(MarketRegime.TRENDING, min(confidence, 1.0), tuple(reasons))

        if volatility <= 0.25 and momentum <= 0.35:
            confidence = ((1.0 - volatility) + (1.0 - momentum)) / 2.0
            reasons.extend(("low_volatility", "low_momentum"))
            return RegimeAssessment(MarketRegime.QUIET, min(confidence, 1.0), tuple(reasons))

        if trend.strength <= 0.30 and compression < 0.72:
            confidence = ((1.0 - trend.strength) + (1.0 - momentum)) / 2.0
            reasons.extend(("weak_trend", "limited_directional_momentum"))
            return RegimeAssessment(MarketRegime.RANGING, min(confidence, 1.0), tuple(reasons))

        confidence = max(0.35, 1.0 - abs(trend.acceleration) * 0.25)
        reasons.extend(("mixed_state", "no_dominant_regime"))
        return RegimeAssessment(MarketRegime.TRANSITION, min(confidence, 1.0), tuple(reasons))
