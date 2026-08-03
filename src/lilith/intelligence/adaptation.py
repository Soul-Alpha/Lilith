from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
from json import dumps
from typing import Mapping, Protocol

try:
    from enum import StrEnum
except ImportError:  # Python < 3.11
    class StrEnum(str, Enum):
        pass

from .governance import DataQualityReport, GovernanceDecision, LearningRecommendation


class AdaptationStage(StrEnum):
    DISABLED = "DISABLED"
    SHADOW = "SHADOW"
    CANARY = "CANARY"
    LIVE = "LIVE"
    ROLLED_BACK = "ROLLED_BACK"
    HALTED = "HALTED"


class AdaptationAction(StrEnum):
    NOOP = "NOOP"
    START_SHADOW = "START_SHADOW"
    START_CANARY = "START_CANARY"
    PROMOTE_LIVE = "PROMOTE_LIVE"
    ROLLBACK = "ROLLBACK"
    HALT = "HALT"


@dataclass(frozen=True, slots=True)
class AdaptationPolicy:
    enabled: bool = False
    minimum_quality_score: float = 0.90
    minimum_recommendation_score: float = 0.80
    minimum_shadow_samples: int = 100
    minimum_canary_samples: int = 50
    canary_allocation_fraction: float = 0.05
    maximum_canary_allocation_fraction: float = 0.10
    minimum_expectancy_improvement_r: float = 0.10
    maximum_drawdown_percent: float = 0.05
    maximum_loss_streak: int = 3
    maximum_drift_score: float = 0.20
    maximum_portfolio_heat: float = 0.03
    require_pre_authorized_manifest: bool = True


@dataclass(frozen=True, slots=True)
class AdaptationCandidate:
    candidate_id: str
    champion_version: str
    challenger_version: str
    created_at_utc: datetime
    allowed_parameters: Mapping[str, float | int | str | bool]
    manifest_digest: str

    @classmethod
    def create(
        cls,
        *,
        candidate_id: str,
        champion_version: str,
        challenger_version: str,
        allowed_parameters: Mapping[str, float | int | str | bool],
        created_at_utc: datetime | None = None,
    ) -> "AdaptationCandidate":
        created = created_at_utc or datetime.now(timezone.utc)
        if created.tzinfo is None:
            raise ValueError("created timestamp must be timezone-aware")
        payload = {
            "candidate_id": candidate_id,
            "champion_version": champion_version,
            "challenger_version": challenger_version,
            "allowed_parameters": dict(sorted(allowed_parameters.items())),
        }
        digest = sha256(dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        return cls(
            candidate_id=candidate_id,
            champion_version=champion_version,
            challenger_version=challenger_version,
            created_at_utc=created,
            allowed_parameters=dict(allowed_parameters),
            manifest_digest=digest,
        )


@dataclass(frozen=True, slots=True)
class LiveAdaptationEvidence:
    sample_size: int
    expectancy_r: float
    champion_expectancy_r: float
    drawdown_percent: float
    loss_streak: int
    drift_score: float
    portfolio_heat: float
    fatal_errors: int = 0


@dataclass(frozen=True, slots=True)
class AdaptationState:
    candidate_id: str
    stage: AdaptationStage
    active_version: str
    previous_version: str
    allocation_fraction: float
    updated_at_utc: datetime
    sequence: int = 0


@dataclass(frozen=True, slots=True)
class AdaptationDecision:
    action: AdaptationAction
    next_state: AdaptationState
    reasons: tuple[str, ...]
    audit_digest: str


class ActivationAdapter(Protocol):
    """Narrow runtime boundary implemented by the host trading application."""

    def activate(self, candidate: AdaptationCandidate, allocation_fraction: float) -> None: ...

    def rollback(self, previous_version: str) -> None: ...

    def halt(self, reason: str) -> None: ...


class AutonomousAdaptationController:
    """Fail-closed state machine for bounded autonomous live adaptation.

    The controller cannot alter arbitrary strategy state. It can only activate a
    pre-built candidate manifest through the injected adapter and only after
    quality, governance, shadow, canary, portfolio-risk and rollback gates pass.
    """

    def __init__(self, policy: AdaptationPolicy | None = None) -> None:
        self.policy = policy or AdaptationPolicy()
        if not 0 < self.policy.canary_allocation_fraction <= self.policy.maximum_canary_allocation_fraction:
            raise ValueError("canary allocation must be positive and within policy maximum")

    def evaluate(
        self,
        *,
        candidate: AdaptationCandidate,
        state: AdaptationState,
        quality: DataQualityReport,
        recommendation: LearningRecommendation,
        evidence: LiveAdaptationEvidence,
        manifest_authorized: bool,
        kill_switch: bool = False,
        now_utc: datetime | None = None,
    ) -> AdaptationDecision:
        now = now_utc or datetime.now(timezone.utc)
        if now.tzinfo is None:
            raise ValueError("current time must be timezone-aware")
        if state.candidate_id != candidate.candidate_id:
            raise ValueError("state and candidate IDs must match")

        reasons: list[str] = []
        action = AdaptationAction.NOOP
        next_stage = state.stage
        next_version = state.active_version
        allocation = state.allocation_fraction

        fatal_reason = self._fatal_reason(evidence, kill_switch)
        if fatal_reason:
            reasons.append(fatal_reason)
            if state.stage in {AdaptationStage.CANARY, AdaptationStage.LIVE}:
                action = AdaptationAction.ROLLBACK
                next_stage = AdaptationStage.ROLLED_BACK
                next_version = state.previous_version
                allocation = 0.0
            else:
                action = AdaptationAction.HALT
                next_stage = AdaptationStage.HALTED
                allocation = 0.0
        elif not self.policy.enabled:
            reasons.append("autonomous_adaptation_disabled")
            next_stage = AdaptationStage.DISABLED
            allocation = 0.0
        elif self.policy.require_pre_authorized_manifest and not manifest_authorized:
            reasons.append("manifest_not_pre_authorized")
        elif not quality.passed or quality.score < self.policy.minimum_quality_score:
            reasons.extend(quality.reasons)
            reasons.append("data_quality_gate_failed")
        elif recommendation.decision != GovernanceDecision.APPROVE_CANDIDATE:
            reasons.append("governance_candidate_not_approved")
        elif recommendation.score < self.policy.minimum_recommendation_score:
            reasons.append("recommendation_score_below_policy")
        elif evidence.drift_score > self.policy.maximum_drift_score:
            reasons.append("drift_above_policy")
        elif state.stage in {AdaptationStage.DISABLED, AdaptationStage.HALTED, AdaptationStage.ROLLED_BACK}:
            action = AdaptationAction.START_SHADOW
            next_stage = AdaptationStage.SHADOW
            allocation = 0.0
            reasons.append("shadow_evaluation_started")
        elif state.stage == AdaptationStage.SHADOW:
            if evidence.sample_size < self.policy.minimum_shadow_samples:
                reasons.append("shadow_sample_incomplete")
            elif self._improvement(evidence) < self.policy.minimum_expectancy_improvement_r:
                reasons.append("shadow_expectancy_margin_insufficient")
            else:
                action = AdaptationAction.START_CANARY
                next_stage = AdaptationStage.CANARY
                next_version = candidate.challenger_version
                allocation = self.policy.canary_allocation_fraction
                reasons.append("shadow_gates_passed")
        elif state.stage == AdaptationStage.CANARY:
            if evidence.sample_size < self.policy.minimum_canary_samples:
                reasons.append("canary_sample_incomplete")
            elif self._risk_breach(evidence):
                action = AdaptationAction.ROLLBACK
                next_stage = AdaptationStage.ROLLED_BACK
                next_version = state.previous_version
                allocation = 0.0
                reasons.append("canary_risk_gate_breached")
            elif self._improvement(evidence) < self.policy.minimum_expectancy_improvement_r:
                action = AdaptationAction.ROLLBACK
                next_stage = AdaptationStage.ROLLED_BACK
                next_version = state.previous_version
                allocation = 0.0
                reasons.append("canary_expectancy_margin_failed")
            else:
                action = AdaptationAction.PROMOTE_LIVE
                next_stage = AdaptationStage.LIVE
                next_version = candidate.challenger_version
                allocation = 1.0
                reasons.append("canary_gates_passed")
        elif state.stage == AdaptationStage.LIVE:
            if self._risk_breach(evidence) or self._improvement(evidence) < 0:
                action = AdaptationAction.ROLLBACK
                next_stage = AdaptationStage.ROLLED_BACK
                next_version = state.previous_version
                allocation = 0.0
                reasons.append("live_guardrail_breached")
            else:
                reasons.append("live_adaptation_within_guardrails")

        next_state = replace(
            state,
            stage=next_stage,
            active_version=next_version,
            allocation_fraction=allocation,
            updated_at_utc=now,
            sequence=state.sequence + 1,
        )
        digest = self._audit_digest(candidate, state, next_state, action, reasons)
        return AdaptationDecision(action, next_state, tuple(reasons or ["no_state_change"]), digest)

    def apply(self, decision: AdaptationDecision, candidate: AdaptationCandidate, adapter: ActivationAdapter) -> None:
        if decision.action == AdaptationAction.START_CANARY:
            adapter.activate(candidate, decision.next_state.allocation_fraction)
        elif decision.action == AdaptationAction.PROMOTE_LIVE:
            adapter.activate(candidate, 1.0)
        elif decision.action == AdaptationAction.ROLLBACK:
            adapter.rollback(decision.next_state.active_version)
        elif decision.action == AdaptationAction.HALT:
            adapter.halt(decision.reasons[0])

    def _risk_breach(self, evidence: LiveAdaptationEvidence) -> bool:
        return (
            evidence.drawdown_percent > self.policy.maximum_drawdown_percent
            or evidence.loss_streak > self.policy.maximum_loss_streak
            or evidence.portfolio_heat > self.policy.maximum_portfolio_heat
            or evidence.fatal_errors > 0
        )

    @staticmethod
    def _improvement(evidence: LiveAdaptationEvidence) -> float:
        return evidence.expectancy_r - evidence.champion_expectancy_r

    def _fatal_reason(self, evidence: LiveAdaptationEvidence, kill_switch: bool) -> str | None:
        if kill_switch:
            return "global_kill_switch_active"
        if evidence.fatal_errors > 0:
            return "fatal_runtime_error"
        return None

    @staticmethod
    def _audit_digest(
        candidate: AdaptationCandidate,
        current: AdaptationState,
        following: AdaptationState,
        action: AdaptationAction,
        reasons: list[str],
    ) -> str:
        payload = {
            "candidate": candidate.manifest_digest,
            "from": current.stage,
            "to": following.stage,
            "action": action,
            "sequence": following.sequence,
            "reasons": reasons,
        }
        return sha256(dumps(payload, sort_keys=True, default=str, separators=(",", ":")).encode()).hexdigest()
