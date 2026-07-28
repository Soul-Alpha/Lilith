from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from itertools import combinations
from typing import Iterable

from .models import FeatureCombinationResult, SculptorPolicy, TradeObservation


class FeatureSculptor:
    """Ranks observed feature fingerprints without mutating strategy behaviour."""

    def __init__(self, policy: SculptorPolicy | None = None) -> None:
        self.policy = policy or SculptorPolicy()

    def analyse(self, observations: Iterable[TradeObservation]) -> list[FeatureCombinationResult]:
        rows = list(observations)
        grouped: dict[tuple[tuple[str, str], ...], list[TradeObservation]] = defaultdict(list)
        for row in rows:
            names = sorted(row.features)
            for size in range(1, min(self.policy.maximum_combination_size, len(names)) + 1):
                for selected in combinations(names, size):
                    key = tuple((name, self._normalise(row.features[name])) for name in selected)
                    grouped[key].append(row)

        results = [self._evaluate(key, group) for key, group in grouped.items()]
        return sorted(
            results,
            key=lambda result: (
                result.approved,
                result.expectancy_r,
                result.profit_factor,
                result.stability_score,
                result.sample_size,
            ),
            reverse=True,
        )

    def _evaluate(
        self,
        key: tuple[tuple[str, str], ...],
        rows: list[TradeObservation],
    ) -> FeatureCombinationResult:
        pnls = [row.net_pnl for row in rows]
        rs = [row.r_multiple for row in rows]
        wins = sum(value > 0 for value in pnls)
        losses = sum(value < 0 for value in pnls)
        gross_profit = sum((value for value in pnls if value > 0), Decimal("0"))
        gross_loss = abs(sum((value for value in pnls if value < 0), Decimal("0")))
        profit_factor = gross_profit / gross_loss if gross_loss else Decimal("999") if gross_profit else Decimal("0")
        expectancy_pnl = sum(pnls, Decimal("0")) / len(rows)
        expectancy_r = sum(rs, Decimal("0")) / len(rows)
        drawdown = self._max_drawdown(pnls)
        stability = self._stability(rs)

        rejection_reasons: list[str] = []
        if len(rows) < self.policy.minimum_sample:
            rejection_reasons.append("minimum_sample")
        if expectancy_r < self.policy.minimum_expectancy_r:
            rejection_reasons.append("minimum_expectancy_r")
        if profit_factor < self.policy.minimum_profit_factor:
            rejection_reasons.append("minimum_profit_factor")
        if drawdown > self.policy.maximum_drawdown:
            rejection_reasons.append("maximum_drawdown")
        if stability < self.policy.minimum_stability_score:
            rejection_reasons.append("minimum_stability_score")

        names = tuple(name for name, _ in key)
        values = tuple(value for _, value in key)
        fingerprint = "|".join(f"{name}={value}" for name, value in key)
        return FeatureCombinationResult(
            fingerprint=fingerprint,
            feature_names=names,
            feature_values=values,
            sample_size=len(rows),
            wins=wins,
            losses=losses,
            win_rate=wins / len(rows),
            expectancy_pnl=expectancy_pnl,
            expectancy_r=expectancy_r,
            profit_factor=profit_factor,
            max_drawdown=drawdown,
            stability_score=stability,
            approved=not rejection_reasons,
            rejection_reasons=tuple(rejection_reasons),
        )

    @staticmethod
    def _normalise(value: object) -> str:
        if isinstance(value, float):
            return f"{value:.4g}"
        return str(value)

    @staticmethod
    def _max_drawdown(pnls: list[Decimal]) -> Decimal:
        equity = Decimal("0")
        peak = Decimal("0")
        maximum = Decimal("0")
        for pnl in pnls:
            equity += pnl
            peak = max(peak, equity)
            maximum = max(maximum, peak - equity)
        return maximum

    @staticmethod
    def _stability(rs: list[Decimal]) -> float:
        if len(rs) < 4:
            return 0.0
        midpoint = len(rs) // 2
        first = sum(rs[:midpoint], Decimal("0")) / midpoint
        second_rows = rs[midpoint:]
        second = sum(second_rows, Decimal("0")) / len(second_rows)
        if first <= 0 or second <= 0:
            return 0.0
        larger = max(first, second)
        return float(min(first, second) / larger) if larger else 0.0
