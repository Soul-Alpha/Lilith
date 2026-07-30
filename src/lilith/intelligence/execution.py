from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from statistics import fmean
from typing import Sequence

from lilith.forensics.models import EntrySnapshot, LifecycleSnapshot, RealisedOutcome, Side


def _bounded(value: float) -> float:
    return min(max(value, 0.0), 1.0)


def _grade(score: float) -> str:
    if score >= 0.90:
        return "A+"
    if score >= 0.80:
        return "A"
    if score >= 0.70:
        return "B"
    if score >= 0.60:
        return "C"
    if score >= 0.50:
        return "D"
    return "F"


@dataclass(frozen=True, slots=True)
class ExecutionQualityReport:
    trade_id: str
    entry_quality: float
    stop_quality: float
    exit_quality: float
    management_quality: float
    discipline_score: float
    institutional_execution_index: float
    execution_grade: str
    realised_r: float
    mfe_r: float
    mae_r: float
    captured_mfe_ratio: float
    premature_exit: bool
    overextended_hold: bool
    avoidable_stop_out: bool
    time_in_profit_seconds: int
    time_in_loss_seconds: int
    reasons: tuple[str, ...]


class ExecutionIntelligenceEngine:
    """Scores completed trades without producing execution instructions.

    The engine consumes immutable forensic snapshots and returns descriptive
    analytics only. It never submits orders, changes stops, modifies targets,
    or mutates runtime configuration.
    """

    def analyse(
        self,
        entry: EntrySnapshot,
        lifecycle: Sequence[LifecycleSnapshot],
        outcome: RealisedOutcome,
    ) -> ExecutionQualityReport:
        if outcome.trade_id != entry.trade_id:
            raise ValueError("entry and outcome trade IDs must match")
        ordered = sorted(
            (item for item in lifecycle if item.trade_id == entry.trade_id),
            key=lambda item: item.timestamp,
        )
        if not ordered:
            raise ValueError("at least one lifecycle snapshot is required")

        risk = float(entry.initial_risk_distance)
        if risk <= 0:
            raise ValueError("initial risk distance must be positive")
        entry_price = float(entry.filled_entry)
        exit_price = float(outcome.exit_price)
        prices = [self._mark_price(entry.side, item) for item in ordered]
        favourable = [self._signed_move(entry.side, entry_price, price) for price in prices]
        adverse = [-value for value in favourable]
        mfe_r = max(max(favourable), 0.0) / risk
        mae_r = max(max(adverse), 0.0) / risk
        realised_r = self._signed_move(entry.side, entry_price, exit_price) / risk
        captured = _bounded(max(realised_r, 0.0) / max(mfe_r, 1e-12))

        slippage_r = abs(float(entry.slippage)) / risk
        spread_r = abs(float(entry.spread)) / risk
        entry_quality = _bounded(
            0.45 * _bounded(entry.entry_quality_score)
            + 0.25 * _bounded(entry.adjusted_confidence)
            + 0.20 * (1.0 - _bounded(slippage_r))
            + 0.10 * (1.0 - _bounded(spread_r))
        )

        initial_stop_r = abs(float(entry.filled_entry - entry.stop_price)) / risk
        stop_changes = [item.stop_price for item in ordered if item.stop_price is not None]
        stop_instability = 0.0
        if len(stop_changes) > 1:
            stop_instability = sum(a != b for a, b in zip(stop_changes, stop_changes[1:])) / (len(stop_changes) - 1)
        adverse_efficiency = 1.0 - _bounded(mae_r / max(initial_stop_r, 1e-12))
        stop_quality = _bounded(0.65 * adverse_efficiency + 0.35 * (1.0 - stop_instability))

        premature_exit = realised_r > 0 and mfe_r >= max(realised_r * 1.75, realised_r + 0.5)
        overextended_hold = mfe_r > 0.5 and realised_r <= 0 and captured < 0.15
        avoidable_stop_out = realised_r < 0 and mfe_r >= 0.75 and mae_r <= 1.15
        exit_quality = _bounded(
            0.70 * captured
            + 0.20 * (1.0 if realised_r > 0 else 0.0)
            + 0.10 * (0.0 if premature_exit or overextended_hold else 1.0)
        )

        time_in_profit = 0
        time_in_loss = 0
        for current, following in zip(ordered, ordered[1:]):
            seconds = max(int((following.timestamp - current.timestamp).total_seconds()), 0)
            move = self._signed_move(entry.side, entry_price, self._mark_price(entry.side, current))
            if move > 0:
                time_in_profit += seconds
            elif move < 0:
                time_in_loss += seconds
        total_time = time_in_profit + time_in_loss
        profit_time_ratio = time_in_profit / total_time if total_time else 0.5
        management_quality = _bounded(
            0.40 * captured
            + 0.25 * profit_time_ratio
            + 0.20 * (1.0 - _bounded(mae_r / 1.5))
            + 0.15 * (0.0 if overextended_hold else 1.0)
        )

        planned_r = float(entry.planned_reward_to_risk)
        discipline = _bounded(
            0.35 * (1.0 - _bounded(slippage_r))
            + 0.25 * (1.0 - stop_instability)
            + 0.20 * (1.0 if planned_r >= 1.0 else planned_r)
            + 0.20 * (0.0 if avoidable_stop_out else 1.0)
        )
        index = fmean((entry_quality, stop_quality, exit_quality, management_quality, discipline))

        reasons: list[str] = []
        if premature_exit:
            reasons.append("premature_exit")
        if overextended_hold:
            reasons.append("overextended_hold")
        if avoidable_stop_out:
            reasons.append("avoidable_stop_out")
        if slippage_r > 0.10:
            reasons.append("material_entry_slippage")
        if stop_instability > 0.50:
            reasons.append("frequent_stop_adjustment")
        if not reasons:
            reasons.append("execution_within_observed_tolerances")

        return ExecutionQualityReport(
            trade_id=entry.trade_id,
            entry_quality=entry_quality,
            stop_quality=stop_quality,
            exit_quality=exit_quality,
            management_quality=management_quality,
            discipline_score=discipline,
            institutional_execution_index=index,
            execution_grade=_grade(index),
            realised_r=realised_r,
            mfe_r=mfe_r,
            mae_r=mae_r,
            captured_mfe_ratio=captured,
            premature_exit=premature_exit,
            overextended_hold=overextended_hold,
            avoidable_stop_out=avoidable_stop_out,
            time_in_profit_seconds=time_in_profit,
            time_in_loss_seconds=time_in_loss,
            reasons=tuple(reasons),
        )

    @staticmethod
    def _mark_price(side: Side, snapshot: LifecycleSnapshot) -> float:
        return float(snapshot.bid if side == Side.BUY else snapshot.ask)

    @staticmethod
    def _signed_move(side: Side, entry: float, price: float) -> float:
        return price - entry if side == Side.BUY else entry - price
