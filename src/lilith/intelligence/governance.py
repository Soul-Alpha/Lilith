from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from math import exp
from statistics import fmean
from typing import Iterable, Mapping

try:
    from enum import StrEnum
except ImportError:  # Python < 3.11
    class StrEnum(str, Enum):
        pass


class GovernanceDecision(StrEnum):
    HOLD = "HOLD"
    REVIEW = "REVIEW"
    APPROVE_CANDIDATE = "APPROVE_CANDIDATE"
    RETIRE_CANDIDATE = "RETIRE_CANDIDATE"


@dataclass(frozen=True, slots=True)
class DataQualityPolicy:
    minimum_sample_size: int = 30
    minimum_resolved_ratio: float = 0.80
    maximum_missing_feature_ratio: float = 0.10
    maximum_duplicate_ratio: float = 0.01
    maximum_age_hours: float = 48.0


@dataclass(frozen=True, slots=True)
class DataQualityReport:
    passed: bool
    sample_size: int
    resolved_ratio: float
    missing_feature_ratio: float
    duplicate_ratio: float
    age_hours: float
    score: float
    reasons: tuple[str, ...]


class DataQualityGate:
    """Validates evidence before it can enter governed learning review."""

    def __init__(self, policy: DataQualityPolicy | None = None) -> None:
        self.policy = policy or DataQualityPolicy()

    def evaluate(
        self,
        *,
        sample_size: int,
        resolved_count: int,
        missing_feature_count: int,
        total_feature_count: int,
        duplicate_count: int,
        latest_timestamp_utc: datetime,
        now_utc: datetime | None = None,
    ) -> DataQualityReport:
        if latest_timestamp_utc.tzinfo is None:
            raise ValueError("latest timestamp must be timezone-aware")
        now = now_utc or datetime.now(timezone.utc)
        if now.tzinfo is None:
            raise ValueError("current time must be timezone-aware")
        resolved_ratio = resolved_count / sample_size if sample_size else 0.0
        missing_ratio = missing_feature_count / total_feature_count if total_feature_count else 0.0
        duplicate_ratio = duplicate_count / sample_size if sample_size else 0.0
        age_hours = max((now - latest_timestamp_utc).total_seconds() / 3600.0, 0.0)
        checks = {
            "insufficient_sample": sample_size >= self.policy.minimum_sample_size,
            "insufficient_resolved_evidence": resolved_ratio >= self.policy.minimum_resolved_ratio,
            "excessive_missing_features": missing_ratio <= self.policy.maximum_missing_feature_ratio,
            "excessive_duplicates": duplicate_ratio <= self.policy.maximum_duplicate_ratio,
            "stale_evidence": age_hours <= self.policy.maximum_age_hours,
        }
        reasons = tuple(name for name, passed in checks.items() if not passed)
        score = fmean(float(value) for value in checks.values())
        return DataQualityReport(
            passed=not reasons,
            sample_size=sample_size,
            resolved_ratio=resolved_ratio,
            missing_feature_ratio=missing_ratio,
            duplicate_ratio=duplicate_ratio,
            age_hours=age_hours,
            score=score,
            reasons=reasons or ("data_quality_passed",),
        )


@dataclass(frozen=True, slots=True)
class KnowledgePolicy:
    revalidation_interval_days: int = 30
    half_life_days: int = 90
    minimum_effective_sample: float = 20.0
    minimum_expectancy_r: float = 0.05
    minimum_stability: float = 0.45
    maximum_drift_score: float = 0.30
    challenger_margin_r: float = 0.10


@dataclass(frozen=True, slots=True)
class KnowledgeCandidate:
    knowledge_id: str
    version: str
    sample_size: int
    expectancy_r: float
    stability_score: float
    drift_score: float
    last_validated_utc: datetime
    regime_metrics: Mapping[str, float]


@dataclass(frozen=True, slots=True)
class LearningRecommendation:
    knowledge_id: str
    version: str
    decision: GovernanceDecision
    effective_sample_size: float
    age_days: float
    decay_factor: float
    score: float
    reasons: tuple[str, ...]
    requires_human_approval: bool = True


class KnowledgeLifecycleEngine:
    """Produces governed recommendations; it never mutates models or execution."""

    def __init__(self, policy: KnowledgePolicy | None = None) -> None:
        self.policy = policy or KnowledgePolicy()

    def review(
        self,
        candidate: KnowledgeCandidate,
        quality: DataQualityReport,
        *,
        now_utc: datetime | None = None,
    ) -> LearningRecommendation:
        if candidate.last_validated_utc.tzinfo is None:
            raise ValueError("validation timestamp must be timezone-aware")
        now = now_utc or datetime.now(timezone.utc)
        age_days = max((now - candidate.last_validated_utc).total_seconds() / 86400.0, 0.0)
        decay = exp(-0.69314718056 * age_days / max(self.policy.half_life_days, 1))
        effective_sample = candidate.sample_size * decay
        reasons: list[str] = []
        decision = GovernanceDecision.APPROVE_CANDIDATE
        if not quality.passed:
            decision = GovernanceDecision.HOLD
            reasons.extend(quality.reasons)
        if effective_sample < self.policy.minimum_effective_sample:
            decision = GovernanceDecision.REVIEW if decision != GovernanceDecision.HOLD else decision
            reasons.append("aged_below_effective_sample")
        if candidate.expectancy_r < self.policy.minimum_expectancy_r:
            decision = GovernanceDecision.RETIRE_CANDIDATE if quality.passed else GovernanceDecision.HOLD
            reasons.append("expectancy_below_policy")
        if candidate.stability_score < self.policy.minimum_stability:
            decision = GovernanceDecision.REVIEW if decision == GovernanceDecision.APPROVE_CANDIDATE else decision
            reasons.append("stability_below_policy")
        if candidate.drift_score > self.policy.maximum_drift_score:
            decision = GovernanceDecision.REVIEW if decision == GovernanceDecision.APPROVE_CANDIDATE else decision
            reasons.append("material_drift")
        if age_days >= self.policy.revalidation_interval_days:
            if decision == GovernanceDecision.APPROVE_CANDIDATE:
                decision = GovernanceDecision.REVIEW
            reasons.append("revalidation_due")
        score = max(min(
            0.30 * quality.score
            + 0.25 * min(effective_sample / max(self.policy.minimum_effective_sample * 2, 1), 1.0)
            + 0.20 * min(max(candidate.expectancy_r, 0.0) / 0.5, 1.0)
            + 0.15 * min(max(candidate.stability_score, 0.0), 1.0)
            + 0.10 * (1.0 - min(max(candidate.drift_score, 0.0), 1.0)),
            0.0,
        ), 1.0)
        return LearningRecommendation(
            knowledge_id=candidate.knowledge_id,
            version=candidate.version,
            decision=decision,
            effective_sample_size=effective_sample,
            age_days=age_days,
            decay_factor=decay,
            score=score,
            reasons=tuple(reasons or ["candidate_within_governed_tolerances"]),
        )

    def compare(
        self,
        champion: KnowledgeCandidate,
        challenger: KnowledgeCandidate,
        quality: DataQualityReport,
        *,
        now_utc: datetime | None = None,
    ) -> LearningRecommendation:
        recommendation = self.review(challenger, quality, now_utc=now_utc)
        margin = challenger.expectancy_r - champion.expectancy_r
        reasons = list(recommendation.reasons)
        decision = recommendation.decision
        if decision == GovernanceDecision.APPROVE_CANDIDATE and margin < self.policy.challenger_margin_r:
            decision = GovernanceDecision.HOLD
            reasons.append("challenger_margin_insufficient")
        elif margin >= self.policy.challenger_margin_r:
            reasons.append("challenger_outperforms_champion")
        return LearningRecommendation(
            knowledge_id=recommendation.knowledge_id,
            version=recommendation.version,
            decision=decision,
            effective_sample_size=recommendation.effective_sample_size,
            age_days=recommendation.age_days,
            decay_factor=recommendation.decay_factor,
            score=recommendation.score,
            reasons=tuple(reasons),
        )
