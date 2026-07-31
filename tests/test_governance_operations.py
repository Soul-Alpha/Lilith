from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest

from lilith.intelligence import (
    BackfillCheckpointStore,
    DataQualityGate,
    DataQualityPolicy,
    GovernanceDecision,
    InstitutionalBatchRunner,
    InstitutionalReportStore,
    KnowledgeCandidate,
    KnowledgeLifecycleEngine,
    KnowledgePolicy,
    operational_health_snapshot,
)


NOW = datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc)


def test_data_quality_gate_passes_complete_fresh_evidence():
    report = DataQualityGate(DataQualityPolicy(minimum_sample_size=10)).evaluate(
        sample_size=20,
        resolved_count=19,
        missing_feature_count=1,
        total_feature_count=100,
        duplicate_count=0,
        latest_timestamp_utc=NOW - timedelta(hours=2),
        now_utc=NOW,
    )
    assert report.passed is True
    assert report.score == 1.0
    assert report.reasons == ("data_quality_passed",)


def test_data_quality_gate_blocks_stale_incomplete_evidence():
    report = DataQualityGate(DataQualityPolicy(minimum_sample_size=30)).evaluate(
        sample_size=10,
        resolved_count=3,
        missing_feature_count=40,
        total_feature_count=100,
        duplicate_count=2,
        latest_timestamp_utc=NOW - timedelta(days=5),
        now_utc=NOW,
    )
    assert report.passed is False
    assert "insufficient_sample" in report.reasons
    assert "stale_evidence" in report.reasons


def candidate(**changes):
    values = dict(
        knowledge_id="pattern-1",
        version="v1",
        sample_size=100,
        expectancy_r=0.30,
        stability_score=0.80,
        drift_score=0.10,
        last_validated_utc=NOW - timedelta(days=5),
        regime_metrics={"trending": 0.4, "ranging": 0.1},
    )
    values.update(changes)
    return KnowledgeCandidate(**values)


def quality_pass():
    return DataQualityGate(DataQualityPolicy(minimum_sample_size=10)).evaluate(
        sample_size=100,
        resolved_count=95,
        missing_feature_count=0,
        total_feature_count=100,
        duplicate_count=0,
        latest_timestamp_utc=NOW,
        now_utc=NOW,
    )


def test_learning_review_is_recommendation_only_and_requires_approval():
    recommendation = KnowledgeLifecycleEngine().review(candidate(), quality_pass(), now_utc=NOW)
    assert recommendation.decision == GovernanceDecision.APPROVE_CANDIDATE
    assert recommendation.requires_human_approval is True


def test_learning_review_recommends_retirement_for_negative_edge():
    recommendation = KnowledgeLifecycleEngine().review(
        candidate(expectancy_r=-0.2), quality_pass(), now_utc=NOW
    )
    assert recommendation.decision == GovernanceDecision.RETIRE_CANDIDATE
    assert "expectancy_below_policy" in recommendation.reasons


def test_challenger_requires_material_margin():
    engine = KnowledgeLifecycleEngine(KnowledgePolicy(challenger_margin_r=0.10))
    recommendation = engine.compare(
        candidate(expectancy_r=0.25),
        candidate(version="v2", expectancy_r=0.30),
        quality_pass(),
        now_utc=NOW,
    )
    assert recommendation.decision == GovernanceDecision.HOLD
    assert "challenger_margin_insufficient" in recommendation.reasons


@dataclass(frozen=True)
class ExampleReport:
    score: float
    reasons: tuple[str, ...]


def test_report_store_is_append_only(tmp_path):
    store = InstitutionalReportStore(tmp_path / "reports.sqlite3")
    store.append(
        report_id="execution:trade-1:v1",
        report_type="execution",
        subject_id="trade-1",
        version="v1",
        report=ExampleReport(0.8, ("ok",)),
        generated_at_utc=NOW,
    )
    assert store.records(report_type="execution")[0]["payload"]["score"] == 0.8
    with pytest.raises(Exception):
        store.append(
            report_id="execution:trade-1:v1",
            report_type="execution",
            subject_id="trade-1",
            version="v1",
            report=ExampleReport(0.9, ("duplicate",)),
            generated_at_utc=NOW,
        )


def test_batch_runner_counts_duplicates_and_rejections():
    records = [
        {"id": "1", "value": 2},
        {"id": "1", "value": 2},
        {"id": "2", "value": -1},
        {"id": "3", "value": 4},
    ]

    def process(item):
        if item["value"] < 0:
            raise ValueError("negative value")
        return item["value"] * 2

    result = InstitutionalBatchRunner().run(records, process, identity=lambda item: item["id"])
    assert result["processed"] == [4, 8]
    assert result["duplicate_count"] == 1
    assert result["rejected_count"] == 1


def test_checkpoint_and_health_snapshot(tmp_path):
    store = BackfillCheckpointStore(tmp_path / "checkpoints.sqlite3")
    store.save("trades", "cursor-100", processed_count=95, rejected_count=5)
    assert store.load("trades")["cursor_value"] == "cursor-100"
    snapshot = operational_health_snapshot(
        observations=100,
        execution_reports=80,
        portfolio_reports=2,
        learning_reviews=5,
        rejected_records=1,
        last_success_utc=datetime.now(timezone.utc),
    )
    assert snapshot["healthy"] is True
    assert snapshot["total_outputs"] == 187
