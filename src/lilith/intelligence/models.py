from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from hashlib import sha256
from json import dumps
from typing import Any, Mapping
from uuid import uuid4


SCHEMA_VERSION = "edith-eids-v1"
FEATURE_VERSION = "edith-intelligence-v1"


class EvidenceStage(StrEnum):
    OBSERVED = "observed"
    CANDIDATE = "candidate"
    VALIDATED = "validated"
    TRUSTED = "trusted"
    MONITORED = "monitored"
    RETIRED = "retired"


class SessionName(StrEnum):
    ASIA = "asia"
    LONDON = "london"
    NEW_YORK = "new_york"
    OVERLAP = "london_new_york_overlap"
    OFF_SESSION = "off_session"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _normalise(value: Any) -> Any:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError("datetime values must be timezone-aware")
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, tuple):
        return [_normalise(item) for item in value]
    if isinstance(value, Mapping):
        return {str(key): _normalise(item) for key, item in sorted(value.items())}
    return value


@dataclass(frozen=True)
class TraceMetadata:
    source_system: str = "edith"
    dataset_id: str = "edith-observations-v1"
    schema_version: str = SCHEMA_VERSION
    feature_version: str = FEATURE_VERSION
    strategy_version: str = "unchanged"
    model_version: str = "observational"
    execution_type: str = "observation"
    observation_mode: str = "observational"
    trace_id: str = field(default_factory=lambda: str(uuid4()))
    created_at_utc: datetime = field(default_factory=utc_now)


@dataclass(frozen=True)
class SessionState:
    name: SessionName
    minutes_since_open: int
    opening_range: float
    session_range: float
    breakout_direction: str | None = None
    breakout_velocity: float = 0.0
    false_breakout: bool = False


@dataclass(frozen=True)
class LiquidityState:
    liquidity_type: str = "none"
    location: str = "unknown"
    internal_external: str = "unknown"
    swept: bool = False
    sweep_depth_atr: float = 0.0
    sweep_duration_bars: int = 0
    recovery_speed_bars: int | None = None
    rejection_strength: float = 0.0
    displacement_atr: float = 0.0


@dataclass(frozen=True)
class TrendState:
    direction: str
    strength: float
    maturity: float
    acceleration: float
    exhaustion: float
    pullback_quality: float
    structure_health: float


@dataclass(frozen=True)
class MarketStateVector:
    session: SessionState
    liquidity: LiquidityState
    trend: TrendState
    volatility_percentile: float
    atr: float
    momentum_score: float
    compression_score: float
    structure_state: str
    vwap_distance_sigma: float | None = None
    higher_timeframe_alignment: float | None = None
    feature_values: Mapping[str, float | int | str | bool | None] = field(default_factory=dict)

    def fingerprint(self) -> str:
        payload = dumps(_normalise(asdict(self)), sort_keys=True, separators=(",", ":"))
        return sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Outcome:
    status: str = "unresolved"
    pnl: float | None = None
    r_multiple: float | None = None
    max_adverse_excursion_r: float | None = None
    max_favourable_excursion_r: float | None = None
    duration_seconds: int | None = None


@dataclass(frozen=True)
class Observation:
    timestamp_utc: datetime
    instrument: str
    timeframe: str
    market_state: MarketStateVector
    outcome: Outcome = field(default_factory=Outcome)
    confidence: float = 0.0
    evidence_stage: EvidenceStage = EvidenceStage.OBSERVED
    metadata: TraceMetadata = field(default_factory=TraceMetadata)
    record_id: str = field(default_factory=lambda: str(uuid4()))
    record_type: str = "market_observation"

    def __post_init__(self) -> None:
        if self.timestamp_utc.tzinfo is None:
            raise ValueError("timestamp_utc must be timezone-aware")
        for name, value in (
            ("confidence", self.confidence),
            ("volatility_percentile", self.market_state.volatility_percentile),
        ):
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1")

    def to_dict(self) -> dict[str, Any]:
        return _normalise(asdict(self))
