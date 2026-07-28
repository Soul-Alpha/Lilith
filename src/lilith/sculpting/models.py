from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from types import MappingProxyType
from typing import Mapping


@dataclass(frozen=True, slots=True)
class TradeObservation:
    trade_id: str
    net_pnl: Decimal
    r_multiple: Decimal
    features: Mapping[str, str | int | float | bool]

    def __post_init__(self) -> None:
        object.__setattr__(self, "features", MappingProxyType(dict(self.features)))


@dataclass(frozen=True, slots=True)
class FeatureCombinationResult:
    fingerprint: str
    feature_names: tuple[str, ...]
    feature_values: tuple[str, ...]
    sample_size: int
    wins: int
    losses: int
    win_rate: float
    expectancy_pnl: Decimal
    expectancy_r: Decimal
    profit_factor: Decimal
    max_drawdown: Decimal
    stability_score: float
    approved: bool
    rejection_reasons: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class SculptorPolicy:
    minimum_sample: int = 30
    minimum_expectancy_r: Decimal = Decimal("0.05")
    minimum_profit_factor: Decimal = Decimal("1.10")
    maximum_drawdown: Decimal = Decimal("10")
    minimum_stability_score: float = 0.60
    maximum_combination_size: int = 2
