from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from statistics import fmean, pstdev
from typing import Iterable, Mapping


def _bounded(value: float) -> float:
    return min(max(value, 0.0), 1.0)


@dataclass(frozen=True, slots=True)
class PortfolioTrade:
    trade_id: str
    timestamp_utc: str
    instrument: str
    timeframe: str
    session: str
    strategy: str
    side: str
    realised_pnl: float
    r_multiple: float
    cash_risk: float
    equity_before: float


@dataclass(frozen=True, slots=True)
class ConcentrationReport:
    instrument: Mapping[str, float]
    timeframe: Mapping[str, float]
    session: Mapping[str, float]
    strategy: Mapping[str, float]
    direction: Mapping[str, float]
    maximum_bucket_share: float
    diversification_score: float


@dataclass(frozen=True, slots=True)
class PortfolioRiskReport:
    sample_size: int
    total_pnl: float
    expectancy_r: float
    return_stability: float
    maximum_drawdown: float
    maximum_drawdown_percent: float
    recovery_factor: float | None
    ulcer_index: float
    value_at_risk_95_r: float
    expected_shortfall_95_r: float
    risk_of_ruin_proxy: float
    average_portfolio_heat: float
    maximum_portfolio_heat: float
    capital_efficiency: float
    concentration: ConcentrationReport
    portfolio_health_score: float
    capital_preservation_score: float
    consistency_score: float
    sustainability_score: float
    warnings: tuple[str, ...]


class PortfolioIntelligenceEngine:
    """Produces descriptive portfolio analytics from resolved trade records.

    Outputs are advisory evidence only. No allocation, sizing, risk limit, or
    execution configuration is changed by this engine.
    """

    def analyse(self, trades: Iterable[PortfolioTrade]) -> PortfolioRiskReport:
        items = list(trades)
        if not items:
            raise ValueError("at least one portfolio trade is required")

        pnl = [item.realised_pnl for item in items]
        r_values = [item.r_multiple for item in items]
        total_pnl = sum(pnl)
        expectancy = fmean(r_values)
        r_deviation = pstdev(r_values) if len(r_values) > 1 else 0.0
        return_stability = 1.0 / (1.0 + r_deviation)

        equity_curve: list[float] = []
        running = items[0].equity_before
        peak = running
        max_drawdown = 0.0
        drawdown_percentages: list[float] = []
        for item in items:
            running += item.realised_pnl
            equity_curve.append(running)
            peak = max(peak, running)
            drawdown = peak - running
            max_drawdown = max(max_drawdown, drawdown)
            drawdown_percentages.append(drawdown / peak if peak > 0 else 0.0)
        maximum_drawdown_percent = max(drawdown_percentages, default=0.0)
        ulcer_index = sqrt(fmean(value * value for value in drawdown_percentages))
        recovery_factor = total_pnl / max_drawdown if max_drawdown > 0 else None

        ordered_r = sorted(r_values)
        tail_count = max(int(len(ordered_r) * 0.05), 1)
        tail = ordered_r[:tail_count]
        value_at_risk = abs(tail[-1])
        expected_shortfall = abs(fmean(tail))

        win_rate = sum(value > 0 for value in r_values) / len(r_values)
        average_win = fmean([value for value in r_values if value > 0]) if any(value > 0 for value in r_values) else 0.0
        average_loss = abs(fmean([value for value in r_values if value < 0])) if any(value < 0 for value in r_values) else 0.0
        edge = win_rate * average_win - (1.0 - win_rate) * average_loss
        risk_of_ruin_proxy = _bounded(0.5 - edge / max(2.0 * (r_deviation + 1e-12), 1e-12))

        heats = [item.cash_risk / item.equity_before for item in items if item.equity_before > 0]
        average_heat = fmean(heats) if heats else 0.0
        maximum_heat = max(heats, default=0.0)
        total_risk = sum(max(item.cash_risk, 0.0) for item in items)
        capital_efficiency = total_pnl / total_risk if total_risk > 0 else 0.0

        concentration = self._concentration(items)
        preservation = _bounded(
            0.45 * (1.0 - _bounded(maximum_drawdown_percent / 0.25))
            + 0.30 * (1.0 - risk_of_ruin_proxy)
            + 0.25 * (1.0 - _bounded(maximum_heat / 0.10))
        )
        consistency = _bounded(
            0.45 * return_stability
            + 0.30 * _bounded(win_rate)
            + 0.25 * (1.0 - _bounded(ulcer_index / 0.20))
        )
        sustainability = _bounded(
            0.35 * preservation
            + 0.25 * consistency
            + 0.20 * concentration.diversification_score
            + 0.20 * _bounded(0.5 + expectancy / 2.0)
        )
        portfolio_health = fmean((preservation, consistency, sustainability, concentration.diversification_score))

        warnings: list[str] = []
        if maximum_drawdown_percent >= 0.20:
            warnings.append("severe_drawdown")
        elif maximum_drawdown_percent >= 0.10:
            warnings.append("material_drawdown")
        if concentration.maximum_bucket_share >= 0.75:
            warnings.append("high_concentration")
        if maximum_heat >= 0.10:
            warnings.append("excessive_portfolio_heat")
        if expectancy <= 0:
            warnings.append("non_positive_expectancy")
        if risk_of_ruin_proxy >= 0.50:
            warnings.append("elevated_risk_of_ruin_proxy")
        if expected_shortfall >= 1.5:
            warnings.append("material_tail_loss")
        if not warnings:
            warnings.append("portfolio_within_observed_tolerances")

        return PortfolioRiskReport(
            sample_size=len(items),
            total_pnl=total_pnl,
            expectancy_r=expectancy,
            return_stability=return_stability,
            maximum_drawdown=max_drawdown,
            maximum_drawdown_percent=maximum_drawdown_percent,
            recovery_factor=recovery_factor,
            ulcer_index=ulcer_index,
            value_at_risk_95_r=value_at_risk,
            expected_shortfall_95_r=expected_shortfall,
            risk_of_ruin_proxy=risk_of_ruin_proxy,
            average_portfolio_heat=average_heat,
            maximum_portfolio_heat=maximum_heat,
            capital_efficiency=capital_efficiency,
            concentration=concentration,
            portfolio_health_score=portfolio_health,
            capital_preservation_score=preservation,
            consistency_score=consistency,
            sustainability_score=sustainability,
            warnings=tuple(warnings),
        )

    def _concentration(self, items: list[PortfolioTrade]) -> ConcentrationReport:
        instrument = self._shares(items, "instrument")
        timeframe = self._shares(items, "timeframe")
        session = self._shares(items, "session")
        strategy = self._shares(items, "strategy")
        direction = self._shares(items, "side")
        all_shares = [*instrument.values(), *timeframe.values(), *session.values(), *strategy.values(), *direction.values()]
        maximum = max(all_shares, default=1.0)
        diversification = 1.0 - maximum
        return ConcentrationReport(
            instrument=instrument,
            timeframe=timeframe,
            session=session,
            strategy=strategy,
            direction=direction,
            maximum_bucket_share=maximum,
            diversification_score=_bounded(diversification),
        )

    @staticmethod
    def _shares(items: list[PortfolioTrade], field: str) -> dict[str, float]:
        weights: dict[str, float] = {}
        for item in items:
            key = str(getattr(item, field))
            weights[key] = weights.get(key, 0.0) + max(item.cash_risk, 0.0)
        total = sum(weights.values())
        if total <= 0:
            total = float(len(items))
            weights = {}
            for item in items:
                key = str(getattr(item, field))
                weights[key] = weights.get(key, 0.0) + 1.0
        return {key: value / total for key, value in sorted(weights.items())}
