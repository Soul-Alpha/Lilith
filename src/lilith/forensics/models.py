from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType
from typing import Mapping


class Side(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class ExitReason(StrEnum):
    TAKE_PROFIT = "TAKE_PROFIT"
    STOP_LOSS = "STOP_LOSS"
    TRAILING_STOP = "TRAILING_STOP"
    BREAKEVEN = "BREAKEVEN"
    MANUAL = "MANUAL"
    TIMEOUT = "TIMEOUT"
    BROKER = "BROKER"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class FeatureEvidence:
    values: Mapping[str, float | int | str | bool | None] = field(default_factory=dict)
    votes: Mapping[str, float] = field(default_factory=dict)
    weights: Mapping[str, float] = field(default_factory=dict)
    passed_conditions: tuple[str, ...] = ()
    failed_conditions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "values", MappingProxyType(dict(self.values)))
        object.__setattr__(self, "votes", MappingProxyType(dict(self.votes)))
        object.__setattr__(self, "weights", MappingProxyType(dict(self.weights)))


@dataclass(frozen=True, slots=True)
class EntrySnapshot:
    trade_id: str
    signal_id: str
    symbol: str
    timeframe: str
    side: Side
    timestamp: datetime
    requested_entry: Decimal
    filled_entry: Decimal
    stop_price: Decimal
    target_price: Decimal
    volume: Decimal
    balance: Decimal
    equity: Decimal
    spread: Decimal = Decimal("0")
    slippage: Decimal = Decimal("0")
    cash_risk: Decimal = Decimal("0")
    risk_percent: Decimal = Decimal("0")
    session: str = "UNKNOWN"
    regime: str = "UNKNOWN"
    structure: str = "UNKNOWN"
    higher_timeframe_bias: str = "UNKNOWN"
    raw_confidence: float = 0.0
    adjusted_confidence: float = 0.0
    entry_quality_score: float = 0.0
    execution_threshold: float = 0.0
    strategy_version: str = "unversioned"
    configuration_hash: str = "unknown"
    evidence: FeatureEvidence = field(default_factory=FeatureEvidence)

    def __post_init__(self) -> None:
        if self.timestamp.tzinfo is None:
            object.__setattr__(self, "timestamp", self.timestamp.replace(tzinfo=timezone.utc))
        if self.volume <= 0:
            raise ValueError("volume must be positive")
        if self.stop_price == self.filled_entry:
            raise ValueError("stop price must differ from entry")
        if self.target_price == self.filled_entry:
            raise ValueError("target price must differ from entry")

    @property
    def initial_risk_distance(self) -> Decimal:
        return abs(self.filled_entry - self.stop_price)

    @property
    def target_distance(self) -> Decimal:
        return abs(self.target_price - self.filled_entry)

    @property
    def planned_reward_to_risk(self) -> Decimal:
        if self.initial_risk_distance == 0:
            return Decimal("0")
        return self.target_distance / self.initial_risk_distance


@dataclass(frozen=True, slots=True)
class LifecycleSnapshot:
    trade_id: str
    timestamp: datetime
    bid: Decimal
    ask: Decimal
    stop_price: Decimal | None = None
    target_price: Decimal | None = None
    floating_pnl: Decimal = Decimal("0")
    structure: str = "UNKNOWN"
    regime: str = "UNKNOWN"

    def __post_init__(self) -> None:
        if self.timestamp.tzinfo is None:
            object.__setattr__(self, "timestamp", self.timestamp.replace(tzinfo=timezone.utc))


@dataclass(frozen=True, slots=True)
class RealisedOutcome:
    trade_id: str
    exit_timestamp: datetime
    exit_price: Decimal
    gross_profit: Decimal
    commission: Decimal = Decimal("0")
    swap: Decimal = Decimal("0")
    fee: Decimal = Decimal("0")
    broker_reason: str = ""
    exit_reason: ExitReason = ExitReason.UNKNOWN

    def __post_init__(self) -> None:
        if self.exit_timestamp.tzinfo is None:
            object.__setattr__(self, "exit_timestamp", self.exit_timestamp.replace(tzinfo=timezone.utc))

    @property
    def net_realised_pnl(self) -> Decimal:
        return self.gross_profit + self.commission + self.swap + self.fee


@dataclass(frozen=True, slots=True)
class TradeForensicReport:
    trade_id: str
    exit_reason: ExitReason
    net_realised_pnl: Decimal
    r_multiple: Decimal
    mfe_price: Decimal
    mae_price: Decimal
    mfe_r: Decimal
    mae_r: Decimal
    peak_floating_pnl: Decimal
    trough_floating_pnl: Decimal
    time_in_profit_seconds: int
    time_in_loss_seconds: int
    direction_quality: str
    entry_quality: str
    stop_quality: str
    target_quality: str
    management_quality: str
    primary_cause: str
    contributing_factors: tuple[str, ...]
