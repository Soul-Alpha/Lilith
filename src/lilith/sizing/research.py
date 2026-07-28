from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable


@dataclass(frozen=True, slots=True)
class SizingObservation:
    trade_id: str
    r_multiple: Decimal
    confidence: Decimal = Decimal("1")
    volatility_ratio: Decimal = Decimal("1")


@dataclass(frozen=True, slots=True)
class SizingPolicyResult:
    policy: str
    final_equity: Decimal
    net_pnl: Decimal
    max_drawdown: Decimal
    risk_of_ruin_triggered: bool


class PositionSizingResearch:
    """Counterfactual sizing only; this class cannot submit or modify orders."""

    def compare(
        self,
        observations: Iterable[SizingObservation],
        *,
        starting_equity: Decimal,
        base_risk_percent: Decimal = Decimal("0.01"),
        ruin_floor_percent: Decimal = Decimal("0.50"),
    ) -> list[SizingPolicyResult]:
        rows = list(observations)
        policies = {
            "fixed_risk": lambda row: base_risk_percent,
            "confidence_scaled": lambda row: base_risk_percent * self._clamp(row.confidence, Decimal("0.25"), Decimal("1.25")),
            "volatility_scaled": lambda row: base_risk_percent / self._clamp(row.volatility_ratio, Decimal("0.50"), Decimal("2.00")),
        }
        return [
            self._simulate(name, rows, sizing, starting_equity, ruin_floor_percent)
            for name, sizing in policies.items()
        ]

    def _simulate(self, name, rows, sizing, starting_equity, ruin_floor_percent):
        equity = starting_equity
        peak = starting_equity
        max_drawdown = Decimal("0")
        ruin_floor = starting_equity * ruin_floor_percent
        ruined = False
        for row in rows:
            risk_cash = equity * sizing(row)
            equity += risk_cash * row.r_multiple
            peak = max(peak, equity)
            max_drawdown = max(max_drawdown, peak - equity)
            if equity <= ruin_floor:
                ruined = True
                break
        return SizingPolicyResult(
            policy=name,
            final_equity=equity,
            net_pnl=equity - starting_equity,
            max_drawdown=max_drawdown,
            risk_of_ruin_triggered=ruined,
        )

    @staticmethod
    def _clamp(value: Decimal, minimum: Decimal, maximum: Decimal) -> Decimal:
        return max(minimum, min(maximum, value))
