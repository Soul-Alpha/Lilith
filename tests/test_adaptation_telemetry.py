from __future__ import annotations

from datetime import datetime, timezone

from lilith.intelligence import (
    AdaptationAction,
    AdaptationCandidate,
    AdaptationDecision,
    AdaptationPolicy,
    AdaptationStage,
    AdaptationState,
    AdaptationTelemetryPaths,
    AdaptationTelemetryStore,
    DataQualityReport,
    GovernanceDecision,
    LearningRecommendation,
    LiveAdaptationEvidence,
)


def test_store_writes_latest_snapshot_and_append_only_event(tmp_path):
    now = datetime(2026, 7, 31, tzinfo=timezone.utc)
    candidate = AdaptationCandidate.create(
        candidate_id="candidate-1",
        champion_version="v1",
        challenger_version="v2",
        allowed_parameters={"threshold": 0.8},
        created_at_utc=now,
    )
    state = AdaptationState(
        candidate_id="candidate-1",
        stage=AdaptationStage.CANARY,
        active_version="v2",
        previous_version="v1",
        allocation_fraction=0.05,
        updated_at_utc=now,
        sequence=2,
    )
    decision = AdaptationDecision(
        action=AdaptationAction.START_CANARY,
        next_state=state,
        reasons=("shadow_gates_passed",),
        audit_digest="audit-1",
    )
    quality = DataQualityReport(True, 150, 1.0, 0.0, 0.0, 1.0, 1.0, ("data_quality_passed",))
    recommendation = LearningRecommendation(
        knowledge_id="k1",
        version="v2",
        decision=GovernanceDecision.APPROVE_CANDIDATE,
        effective_sample_size=150.0,
        age_days=0.0,
        decay_factor=1.0,
        score=0.95,
        reasons=("candidate_within_governed_tolerances",),
    )
    evidence = LiveAdaptationEvidence(150, 0.35, 0.20, 0.01, 1, 0.05, 0.01)
    paths = AdaptationTelemetryPaths(tmp_path / "state.json", tmp_path / "events.jsonl")
    store = AdaptationTelemetryStore(paths)

    snapshot = store.record(
        candidate=candidate,
        decision=decision,
        quality=quality,
        recommendation=recommendation,
        evidence=evidence,
        policy=AdaptationPolicy(enabled=True),
        manifest_authorized=True,
        kill_switch=False,
        recorded_at_utc=now,
    )

    assert snapshot["state"]["stage"] == "CANARY"
    assert snapshot["guardrails"]["data_quality"] is True
    assert snapshot["guardrails"]["expectancy_margin"] is True
    assert snapshot["expectancy_improvement_r"] == 0.15
    assert store.latest()["telemetry_digest"] == snapshot["telemetry_digest"]
    assert len(paths.events_path.read_text(encoding="utf-8").splitlines()) == 1


def test_store_marks_failed_guardrails(tmp_path):
    now = datetime(2026, 7, 31, tzinfo=timezone.utc)
    candidate = AdaptationCandidate.create(
        candidate_id="candidate-2",
        champion_version="v1",
        challenger_version="v2",
        allowed_parameters={},
        created_at_utc=now,
    )
    state = AdaptationState("candidate-2", AdaptationStage.HALTED, "v1", "v1", 0.0, now, 1)
    decision = AdaptationDecision(AdaptationAction.HALT, state, ("global_kill_switch_active",), "audit-2")
    quality = DataQualityReport(False, 10, 0.5, 0.2, 0.1, 80.0, 0.2, ("insufficient_sample",))
    recommendation = LearningRecommendation("k2", "v2", GovernanceDecision.HOLD, 10.0, 0.0, 1.0, 0.2, ("hold",))
    evidence = LiveAdaptationEvidence(10, -0.2, 0.1, 0.10, 5, 0.5, 0.08, 1)
    store = AdaptationTelemetryStore(AdaptationTelemetryPaths(tmp_path / "state.json", tmp_path / "events.jsonl"))

    snapshot = store.record(
        candidate=candidate,
        decision=decision,
        quality=quality,
        recommendation=recommendation,
        evidence=evidence,
        policy=AdaptationPolicy(enabled=True),
        manifest_authorized=False,
        kill_switch=True,
        recorded_at_utc=now,
    )

    assert snapshot["guardrails"]["data_quality"] is False
    assert snapshot["guardrails"]["kill_switch_clear"] is False
    assert snapshot["guardrails"]["fatal_errors"] is False
