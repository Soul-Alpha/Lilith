from datetime import datetime, timezone

from lilith.intelligence.adaptation import (
    AdaptationAction,
    AdaptationCandidate,
    AdaptationPolicy,
    AdaptationStage,
    AdaptationState,
    AutonomousAdaptationController,
    LiveAdaptationEvidence,
)
from lilith.intelligence.governance import DataQualityReport, GovernanceDecision, LearningRecommendation

NOW = datetime(2026, 7, 31, tzinfo=timezone.utc)


def quality(passed: bool = True) -> DataQualityReport:
    return DataQualityReport(passed, 200, 1.0, 0.0, 0.0, 1.0, 1.0 if passed else 0.4, ("data_quality_passed",) if passed else ("stale_evidence",))


def recommendation() -> LearningRecommendation:
    return LearningRecommendation("edge", "v2", GovernanceDecision.APPROVE_CANDIDATE, 100.0, 1.0, 0.99, 0.95, ("candidate_within_governed_tolerances",))


def evidence(samples: int, expectancy: float = 0.35, drawdown: float = 0.01) -> LiveAdaptationEvidence:
    return LiveAdaptationEvidence(samples, expectancy, 0.15, drawdown, 0, 0.05, 0.01)


def candidate() -> AdaptationCandidate:
    return AdaptationCandidate.create(candidate_id="c1", champion_version="v1", challenger_version="v2", allowed_parameters={"confidence_threshold": 0.82}, created_at_utc=NOW)


def state(stage: AdaptationStage) -> AdaptationState:
    return AdaptationState("c1", stage, "v1" if stage != AdaptationStage.CANARY else "v2", "v1", 0.0, NOW)


def controller() -> AutonomousAdaptationController:
    return AutonomousAdaptationController(AdaptationPolicy(enabled=True, minimum_shadow_samples=100, minimum_canary_samples=50))


def test_disabled_by_default_is_fail_closed():
    decision = AutonomousAdaptationController().evaluate(candidate=candidate(), state=state(AdaptationStage.DISABLED), quality=quality(), recommendation=recommendation(), evidence=evidence(100), manifest_authorized=True, now_utc=NOW)
    assert decision.action == AdaptationAction.NOOP
    assert decision.next_state.stage == AdaptationStage.DISABLED


def test_shadow_then_canary_then_live():
    first = controller().evaluate(candidate=candidate(), state=state(AdaptationStage.DISABLED), quality=quality(), recommendation=recommendation(), evidence=evidence(0), manifest_authorized=True, now_utc=NOW)
    assert first.action == AdaptationAction.START_SHADOW
    second = controller().evaluate(candidate=candidate(), state=first.next_state, quality=quality(), recommendation=recommendation(), evidence=evidence(100), manifest_authorized=True, now_utc=NOW)
    assert second.action == AdaptationAction.START_CANARY
    assert second.next_state.allocation_fraction == 0.05
    third = controller().evaluate(candidate=candidate(), state=second.next_state, quality=quality(), recommendation=recommendation(), evidence=evidence(50), manifest_authorized=True, now_utc=NOW)
    assert third.action == AdaptationAction.PROMOTE_LIVE
    assert third.next_state.stage == AdaptationStage.LIVE


def test_canary_drawdown_breach_rolls_back():
    decision = controller().evaluate(candidate=candidate(), state=state(AdaptationStage.CANARY), quality=quality(), recommendation=recommendation(), evidence=evidence(50, drawdown=0.20), manifest_authorized=True, now_utc=NOW)
    assert decision.action == AdaptationAction.ROLLBACK
    assert decision.next_state.active_version == "v1"


def test_kill_switch_rolls_back_live():
    live = AdaptationState("c1", AdaptationStage.LIVE, "v2", "v1", 1.0, NOW)
    decision = controller().evaluate(candidate=candidate(), state=live, quality=quality(), recommendation=recommendation(), evidence=evidence(100), manifest_authorized=True, kill_switch=True, now_utc=NOW)
    assert decision.action == AdaptationAction.ROLLBACK
    assert "global_kill_switch_active" in decision.reasons


def test_unapproved_manifest_cannot_progress():
    decision = controller().evaluate(candidate=candidate(), state=state(AdaptationStage.SHADOW), quality=quality(), recommendation=recommendation(), evidence=evidence(100), manifest_authorized=False, now_utc=NOW)
    assert decision.action == AdaptationAction.NOOP
    assert "manifest_not_pre_authorized" in decision.reasons


def test_poor_quality_cannot_progress():
    decision = controller().evaluate(candidate=candidate(), state=state(AdaptationStage.SHADOW), quality=quality(False), recommendation=recommendation(), evidence=evidence(100), manifest_authorized=True, now_utc=NOW)
    assert decision.action == AdaptationAction.NOOP
    assert "data_quality_gate_failed" in decision.reasons
