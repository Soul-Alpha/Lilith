from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import time
from enum import Enum
from typing import Any

try:
    from enum import StrEnum
except ImportError:  # Python < 3.11
    class StrEnum(str, Enum):
        pass


class Direction(StrEnum):
    BULLISH = "bullish"
    BEARISH = "bearish"


class Outcome(StrEnum):
    WIN = "win"
    LOSS = "loss"
    OPEN = "open"
    EXPIRED = "expired"
    NO_FILL = "no_fill"


@dataclass(frozen=True)
class AMDStructureConfig:
    strategy_version: str = "jaxter-amd-structure-v1"
    timezone: str = "UTC"
    asian_start: time = time(0, 0)
    asian_end: time = time(6, 0)
    london_start: time = time(7, 0)
    london_end: time = time(10, 0)
    distribution_end: time = time(16, 0)
    swing_window: int = 2
    displacement_body_atr: float = 0.8
    sharp_wick_atr: float = 0.35
    max_manipulation_bars: int = 12
    target_r: float = 2.0
    minimum_target_r: float = 1.5
    stop_buffer_atr: float = 0.05
    risk_fraction: float = 0.005
    one_trade_per_session: bool = True

    def __post_init__(self) -> None:
        if self.swing_window < 1:
            raise ValueError("swing_window must be positive")
        if not 0 < self.risk_fraction <= 0.01:
            raise ValueError("risk_fraction must be within (0, 0.01]")
        if self.target_r < self.minimum_target_r:
            raise ValueError("target_r cannot be below minimum_target_r")


@dataclass(frozen=True)
class EntryZone:
    lower: float
    upper: float
    order_block_lower: float
    order_block_upper: float
    fvg_lower: float
    fvg_upper: float


@dataclass(frozen=True)
class AMDStructureSignal:
    signal_id: str
    session_date: str
    symbol: str
    timeframe: str
    direction: Direction
    asian_high: float
    asian_low: float
    sweep_price: float
    sweep_time: str
    choch_time: str
    bos_time: str
    entry_zone: EntryZone
    entry_price: float
    stop_price: float
    target_price: float
    target_r: float
    quality_score: float
    reasons: tuple[str, ...]
    strategy_version: str
    observational_only: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BacktestTrade:
    signal: AMDStructureSignal
    entry_time: str | None
    exit_time: str | None
    outcome: Outcome
    realised_r: float
    bars_held: int
    maximum_favourable_r: float
    maximum_adverse_r: float

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["outcome"] = self.outcome.value
        payload["signal"]["direction"] = self.signal.direction.value
        return payload
