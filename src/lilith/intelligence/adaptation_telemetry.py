from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
from json import dumps, loads
from pathlib import Path
from typing import Any, Mapping

from .adaptation import (
    AdaptationCandidate,
    AdaptationDecision,
    AdaptationPolicy,
    LiveAdaptationEvidence,
)
from .governance import DataQualityReport, LearningRecommendation


def _json_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


@dataclass(frozen=True, slots=True)
class AdaptationTelemetryPaths:
    state_path: Path = Path("data/adaptation_state.json")
    events_path: Path = Path("data/adaptation_events.jsonl")


class AdaptationTelemetryStore:
    """Persists dashboard-ready adaptation snapshots and append-only audit events."""

    def __init__(self, paths: AdaptationTelemetryPaths | None = None) -> None:
        self.paths = paths or AdaptationTelemetryPaths()

    def record(
        self,
        *,
        candidate: AdaptationCandidate,
        decision: AdaptationDecision,
        quality: DataQualityReport,
        recommendation: LearningRecommendation,
        evidence: LiveAdaptationEvidence,
        policy: AdaptationPolicy,
        manifest_authorized: bool,
        kill_switch: bool,
        recorded_at_utc: datetime | None = None,
    ) -> dict[str, Any]:
        recorded_at = recorded_at_utc or datetime.now(timezone.utc)
        if recorded_at.tzinfo is None:
            raise ValueError("recorded timestamp must be timezone-aware")

        # Normalize a derived telemetry value so equivalent decimal evidence has
        # stable JSON, dashboard, digest, and test representation. This does not
        # alter adaptation decisions or policy thresholds.
        improvement = round(evidence.expectancy_r - evidence.champion_expectancy_r, 12)
        guardrails = {
            "data_quality": quality.passed and quality.score >= policy.minimum_quality_score,
            "governance_approval": recommendation.decision.value == "APPROVE_CANDIDATE",
            "recommendation_score": recommendation.score >= policy.minimum_recommendation_score,
            "manifest_authorized": manifest_authorized,
            "shadow_samples": evidence.sample_size >= policy.minimum_shadow_samples,
            "canary_samples": evidence.sample_size >= policy.minimum_canary_samples,
            "expectancy_margin": improvement >= policy.minimum_expectancy_improvement_r,
            "drift": evidence.drift_score <= policy.maximum_drift_score,
            "drawdown": evidence.drawdown_percent <= policy.maximum_drawdown_percent,
            "loss_streak": evidence.loss_streak <= policy.maximum_loss_streak,
            "portfolio_heat": evidence.portfolio_heat <= policy.maximum_portfolio_heat,
            "fatal_errors": evidence.fatal_errors == 0,
            "kill_switch_clear": not kill_switch,
        }
        snapshot: dict[str, Any] = {
            "schema_version": "edith-adaptation-telemetry-v1",
            "recorded_at_utc": recorded_at.astimezone(timezone.utc).isoformat(),
            "candidate": _json_value(asdict(candidate)),
            "state": _json_value(asdict(decision.next_state)),
            "decision": {
                "action": decision.action.value,
                "reasons": list(decision.reasons),
                "audit_digest": decision.audit_digest,
            },
            "quality": _json_value(asdict(quality)),
            "recommendation": _json_value(asdict(recommendation)),
            "evidence": _json_value(asdict(evidence)),
            "policy": _json_value(asdict(policy)),
            "guardrails": guardrails,
            "expectancy_improvement_r": improvement,
            "manifest_authorized": manifest_authorized,
            "kill_switch": kill_switch,
        }
        canonical = dumps(snapshot, sort_keys=True, separators=(",", ":"), default=str)
        snapshot["telemetry_digest"] = sha256(canonical.encode()).hexdigest()

        self.paths.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.paths.events_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.paths.state_path.with_suffix(self.paths.state_path.suffix + ".tmp")
        temporary.write_text(dumps(snapshot, indent=2, sort_keys=True), encoding="utf-8")
        temporary.replace(self.paths.state_path)
        with self.paths.events_path.open("a", encoding="utf-8") as handle:
            handle.write(dumps(snapshot, sort_keys=True, separators=(",", ":")) + "\n")
        return snapshot

    def latest(self) -> dict[str, Any]:
        if not self.paths.state_path.exists():
            return {}
        value = loads(self.paths.state_path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("adaptation state telemetry must contain a JSON object")
        return value
