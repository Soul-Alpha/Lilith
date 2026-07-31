from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from statistics import fmean
from typing import Iterable, Sequence

from .models import Observation


@dataclass(frozen=True)
class ProbabilityEstimate:
    pattern_id: str
    probability_of_positive_r: float
    confidence_low: float
    confidence_high: float
    sample_size: int
    prior_strength: float
    brier_score: float | None
    calibration_error: float | None


@dataclass(frozen=True)
class DriftAssessment:
    drift_detected: bool
    score: float
    baseline_sample: int
    recent_sample: int
    reasons: tuple[str, ...]


class BayesianProbabilityEngine:
    """Beta-binomial probability estimates with explicit uncertainty.

    A weak symmetric prior prevents small samples from reporting false certainty.
    The output is analytical evidence only and cannot approve execution.
    """

    def __init__(self, prior_alpha: float = 1.0, prior_beta: float = 1.0) -> None:
        if prior_alpha <= 0 or prior_beta <= 0:
            raise ValueError("prior parameters must be positive")
        self.prior_alpha = prior_alpha
        self.prior_beta = prior_beta

    def estimate(self, pattern_id: str, observations: Iterable[Observation]) -> ProbabilityEstimate:
        resolved = [item for item in observations if item.outcome.r_multiple is not None]
        wins = sum(1 for item in resolved if item.outcome.r_multiple > 0)
        losses = len(resolved) - wins
        alpha = self.prior_alpha + wins
        beta = self.prior_beta + losses
        probability = alpha / (alpha + beta)
        variance = (alpha * beta) / (((alpha + beta) ** 2) * (alpha + beta + 1.0))
        radius = 1.96 * sqrt(variance)

        reported = [item.confidence for item in resolved]
        outcomes = [1.0 if item.outcome.r_multiple > 0 else 0.0 for item in resolved]
        brier = fmean((p - y) ** 2 for p, y in zip(reported, outcomes)) if reported else None
        calibration = abs(fmean(reported) - fmean(outcomes)) if reported else None

        return ProbabilityEstimate(
            pattern_id=pattern_id,
            probability_of_positive_r=probability,
            confidence_low=max(probability - radius, 0.0),
            confidence_high=min(probability + radius, 1.0),
            sample_size=len(resolved),
            prior_strength=self.prior_alpha + self.prior_beta,
            brier_score=brier,
            calibration_error=calibration,
        )


class DriftMonitor:
    """Compares recent and baseline evidence without mutating learned patterns."""

    def assess(
        self,
        baseline: Sequence[Observation],
        recent: Sequence[Observation],
        *,
        probability_threshold: float = 0.15,
        expectancy_threshold_r: float = 0.25,
    ) -> DriftAssessment:
        baseline_r = [item.outcome.r_multiple for item in baseline if item.outcome.r_multiple is not None]
        recent_r = [item.outcome.r_multiple for item in recent if item.outcome.r_multiple is not None]
        if not baseline_r or not recent_r:
            return DriftAssessment(False, 0.0, len(baseline_r), len(recent_r), ("insufficient_resolved_evidence",))

        baseline_probability = sum(value > 0 for value in baseline_r) / len(baseline_r)
        recent_probability = sum(value > 0 for value in recent_r) / len(recent_r)
        probability_shift = abs(recent_probability - baseline_probability)
        expectancy_shift = abs(fmean(recent_r) - fmean(baseline_r))
        probability_component = probability_shift / max(probability_threshold, 1e-12)
        expectancy_component = expectancy_shift / max(expectancy_threshold_r, 1e-12)
        score = min(max(probability_component, expectancy_component), 10.0)
        reasons: list[str] = []
        if probability_shift >= probability_threshold:
            reasons.append("positive_outcome_probability_shift")
        if expectancy_shift >= expectancy_threshold_r:
            reasons.append("expectancy_shift")
        return DriftAssessment(
            drift_detected=bool(reasons),
            score=score,
            baseline_sample=len(baseline_r),
            recent_sample=len(recent_r),
            reasons=tuple(reasons) or ("within_thresholds",),
        )
