from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from statistics import fmean, pstdev
from typing import Iterable

from .models import EvidenceStage, Observation


@dataclass(frozen=True)
class PatternDNA:
    pattern_id: str
    sample_size: int
    resolved_sample_size: int
    win_rate: float
    expectancy_r: float
    profit_factor: float | None
    average_r: float
    r_stddev: float
    confidence_low: float
    confidence_high: float
    stability_score: float
    evidence_stage: EvidenceStage
    last_observed_utc: str


@dataclass(frozen=True)
class EvidencePolicy:
    candidate_sample: int = 20
    validated_sample: int = 50
    trusted_sample: int = 150
    minimum_positive_expectancy_r: float = 0.05
    minimum_stability: float = 0.45


class PatternDNAEngine:
    """Groups identical deterministic state fingerprints and quantifies outcomes."""

    def __init__(self, policy: EvidencePolicy | None = None) -> None:
        self.policy = policy or EvidencePolicy()

    def discover(self, observations: Iterable[Observation]) -> list[PatternDNA]:
        groups: dict[str, list[Observation]] = {}
        for observation in observations:
            groups.setdefault(observation.market_state.fingerprint(), []).append(observation)
        return [self._summarise(pattern_id, items) for pattern_id, items in sorted(groups.items())]

    def _summarise(self, pattern_id: str, observations: list[Observation]) -> PatternDNA:
        ordered = sorted(observations, key=lambda item: item.timestamp_utc)
        returns = [item.outcome.r_multiple for item in ordered if item.outcome.r_multiple is not None]
        resolved = len(returns)
        wins = [value for value in returns if value > 0]
        losses = [value for value in returns if value < 0]
        win_rate = len(wins) / resolved if resolved else 0.0
        expectancy = fmean(returns) if returns else 0.0
        deviation = pstdev(returns) if len(returns) > 1 else 0.0
        average_r = expectancy
        profit_factor = None
        if losses:
            profit_factor = sum(wins) / abs(sum(losses)) if sum(losses) else None
        interval = 1.96 * sqrt((win_rate * (1.0 - win_rate)) / resolved) if resolved else 0.0
        stability = 1.0 / (1.0 + deviation)
        stage = self._stage(resolved, expectancy, stability)
        return PatternDNA(
            pattern_id=pattern_id,
            sample_size=len(ordered),
            resolved_sample_size=resolved,
            win_rate=win_rate,
            expectancy_r=expectancy,
            profit_factor=profit_factor,
            average_r=average_r,
            r_stddev=deviation,
            confidence_low=max(win_rate - interval, 0.0),
            confidence_high=min(win_rate + interval, 1.0),
            stability_score=stability,
            evidence_stage=stage,
            last_observed_utc=ordered[-1].timestamp_utc.isoformat(),
        )

    def _stage(self, sample: int, expectancy: float, stability: float) -> EvidenceStage:
        if expectancy < self.policy.minimum_positive_expectancy_r:
            return EvidenceStage.RETIRED if sample >= self.policy.validated_sample else EvidenceStage.OBSERVED
        if sample >= self.policy.trusted_sample and stability >= self.policy.minimum_stability:
            return EvidenceStage.TRUSTED
        if sample >= self.policy.validated_sample and stability >= self.policy.minimum_stability:
            return EvidenceStage.VALIDATED
        if sample >= self.policy.candidate_sample:
            return EvidenceStage.CANDIDATE
        return EvidenceStage.OBSERVED


@dataclass(frozen=True)
class FeatureEvidence:
    feature: str
    value: str
    sample_size: int
    expectancy_r: float
    lift_vs_population_r: float


class FeatureEvidenceEngine:
    """Simple, explainable feature lift ranking for Sprint 3 evidence reports."""

    def rank(self, observations: Iterable[Observation]) -> list[FeatureEvidence]:
        items = list(observations)
        population = [item.outcome.r_multiple for item in items if item.outcome.r_multiple is not None]
        baseline = fmean(population) if population else 0.0
        groups: dict[tuple[str, str], list[float]] = {}
        for item in items:
            if item.outcome.r_multiple is None:
                continue
            for name, value in item.market_state.feature_values.items():
                groups.setdefault((name, str(value)), []).append(item.outcome.r_multiple)
        ranked = [
            FeatureEvidence(name, value, len(values), fmean(values), fmean(values) - baseline)
            for (name, value), values in groups.items()
        ]
        return sorted(ranked, key=lambda item: (abs(item.lift_vs_population_r), item.sample_size), reverse=True)
