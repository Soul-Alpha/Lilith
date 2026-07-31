from __future__ import annotations

from typing import Any

from .models import Observation


OLYMPUS_COMPATIBILITY_VERSION = "olympus-transport-v1"


class OlympusCompatibilityAdapter:
    """Transport-only mapping. This module contains no Olympus logic or imports."""

    @staticmethod
    def export_observation(observation: Observation) -> dict[str, Any]:
        native = observation.to_dict()
        return {
            "compatibility_version": OLYMPUS_COMPATIBILITY_VERSION,
            "record_id": native["record_id"],
            "record_type": native["record_type"],
            "timestamp_utc": native["timestamp_utc"],
            "instrument": native["instrument"],
            "timeframe": native["timeframe"],
            "source_system": "edith",
            "dataset_id": native["metadata"]["dataset_id"],
            "schema_version": native["metadata"]["schema_version"],
            "feature_version": native["metadata"]["feature_version"],
            "strategy_version": native["metadata"]["strategy_version"],
            "model_version": native["metadata"]["model_version"],
            "execution_type": native["metadata"]["execution_type"],
            "observation_mode": native["metadata"]["observation_mode"],
            "trace_id": native["metadata"]["trace_id"],
            "created_at_utc": native["metadata"]["created_at_utc"],
            "market_state": native["market_state"],
            "outcome": native["outcome"],
            "confidence": native["confidence"],
            "evidence_stage": native["evidence_stage"],
        }
