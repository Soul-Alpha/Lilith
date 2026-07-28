from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable

from .models import (
    EntrySnapshot,
    ExitReason,
    LifecycleSnapshot,
    RealisedOutcome,
    Side,
    TradeForensicReport,
)


@dataclass(slots=True)
class TradeForensicsService:
    breakeven_tolerance_r: Decimal = Decimal("0.05")
    noise_tolerance_r: Decimal = Decimal("0.15")

    def analyse(
        self,
        entry: EntrySnapshot,
        lifecycle: Iterable[LifecycleSnapshot],
        outcome: RealisedOutcome,
    ) -> TradeForensicReport:
        snapshots = sorted(lifecycle, key=lambda item: item.timestamp)
        if outcome.trade_id != entry.trade_id:
            raise ValueError("outcome trade_id does not match entry")
        if any(item.trade_id != entry.trade_id for item in snapshots):
            raise ValueError("lifecycle contains a different trade_id")

        prices = [entry.filled_entry, *(self._mark_price(entry.side, item) for item in snapshots), outcome.exit_price]
        favourable_moves = [self._signed_move(entry.side, entry.filled_entry, price) for price in prices]
        adverse_moves = [-move for move in favourable_moves]

        mfe = max(Decimal("0"), max(favourable_moves, default=Decimal("0")))
        mae = max(Decimal("0"), max(adverse_moves, default=Decimal("0")))
        risk = entry.initial_risk_distance
        mfe_r = mfe / risk if risk else Decimal("0")
        mae_r = mae / risk if risk else Decimal("0")

        peak_pnl = max((item.floating_pnl for item in snapshots), default=Decimal("0"))
        trough_pnl = min((item.floating_pnl for item in snapshots), default=Decimal("0"))
        time_profit, time_loss = self._time_distribution(snapshots)
        exit_reason = self.classify_exit_reason(entry, outcome)
        realised_r = self._realised_r(entry, outcome)

        direction_quality = "correct" if mfe_r >= Decimal("1") else "incorrect" if mae_r >= Decimal("1") else "inconclusive"
        entry_quality = self._entry_quality(mfe_r, mae_r)
        stop_quality = self._stop_quality(exit_reason, mfe_r, mae_r)
        target_quality = self._target_quality(exit_reason, mfe_r, entry.planned_reward_to_risk)
        management_quality = self._management_quality(exit_reason, mfe_r, peak_pnl, outcome.net_realised_pnl)
        primary_cause, factors = self._diagnosis(exit_reason, direction_quality, entry_quality, stop_quality, management_quality)

        return TradeForensicReport(
            trade_id=entry.trade_id,
            exit_reason=exit_reason,
            net_realised_pnl=outcome.net_realised_pnl,
            r_multiple=realised_r,
            mfe_price=mfe,
            mae_price=mae,
            mfe_r=mfe_r,
            mae_r=mae_r,
            peak_floating_pnl=peak_pnl,
            trough_floating_pnl=trough_pnl,
            time_in_profit_seconds=time_profit,
            time_in_loss_seconds=time_loss,
            direction_quality=direction_quality,
            entry_quality=entry_quality,
            stop_quality=stop_quality,
            target_quality=target_quality,
            management_quality=management_quality,
            primary_cause=primary_cause,
            contributing_factors=factors,
        )

    def classify_exit_reason(self, entry: EntrySnapshot, outcome: RealisedOutcome) -> ExitReason:
        if outcome.exit_reason != ExitReason.UNKNOWN:
            return outcome.exit_reason
        reason = outcome.broker_reason.upper()
        if "TRAIL" in reason:
            return ExitReason.TRAILING_STOP
        if "TP" in reason or "TAKE PROFIT" in reason:
            return ExitReason.TAKE_PROFIT
        if "SL" in reason or "STOP LOSS" in reason:
            return ExitReason.STOP_LOSS
        if "MANUAL" in reason or "CLIENT" in reason:
            return ExitReason.MANUAL

        tolerance = entry.initial_risk_distance * self.breakeven_tolerance_r
        if abs(outcome.exit_price - entry.filled_entry) <= tolerance:
            return ExitReason.BREAKEVEN
        if abs(outcome.exit_price - entry.stop_price) <= tolerance:
            return ExitReason.STOP_LOSS
        if abs(outcome.exit_price - entry.target_price) <= tolerance:
            return ExitReason.TAKE_PROFIT
        return ExitReason.UNKNOWN

    @staticmethod
    def _mark_price(side: Side, snapshot: LifecycleSnapshot) -> Decimal:
        return snapshot.bid if side == Side.BUY else snapshot.ask

    @staticmethod
    def _signed_move(side: Side, entry: Decimal, price: Decimal) -> Decimal:
        return price - entry if side == Side.BUY else entry - price

    def _realised_r(self, entry: EntrySnapshot, outcome: RealisedOutcome) -> Decimal:
        risk = entry.initial_risk_distance
        if not risk:
            return Decimal("0")
        return self._signed_move(entry.side, entry.filled_entry, outcome.exit_price) / risk

    @staticmethod
    def _time_distribution(snapshots: list[LifecycleSnapshot]) -> tuple[int, int]:
        profit = 0
        loss = 0
        for current, following in zip(snapshots, snapshots[1:]):
            duration = max(0, int((following.timestamp - current.timestamp).total_seconds()))
            if current.floating_pnl > 0:
                profit += duration
            elif current.floating_pnl < 0:
                loss += duration
        return profit, loss

    @staticmethod
    def _entry_quality(mfe_r: Decimal, mae_r: Decimal) -> str:
        if mae_r >= Decimal("1") and mfe_r < Decimal("0.25"):
            return "poor_positioning"
        if mae_r >= Decimal("0.5") and mfe_r >= Decimal("1"):
            return "early_but_recoverable"
        if mfe_r >= Decimal("1") and mae_r < Decimal("0.5"):
            return "well_positioned"
        return "unresolved"

    @staticmethod
    def _stop_quality(exit_reason: ExitReason, mfe_r: Decimal, mae_r: Decimal) -> str:
        if exit_reason != ExitReason.STOP_LOSS:
            return "not_applicable"
        if mfe_r >= Decimal("1"):
            return "profit_was_unprotected"
        if mae_r >= Decimal("1") and mfe_r < Decimal("0.25"):
            return "direction_or_entry_failed"
        return "requires_market_replay"

    @staticmethod
    def _target_quality(exit_reason: ExitReason, mfe_r: Decimal, planned_rr: Decimal) -> str:
        if exit_reason == ExitReason.TAKE_PROFIT:
            return "achieved"
        if planned_rr and mfe_r >= planned_rr * Decimal("0.9"):
            return "narrowly_missed"
        if mfe_r < Decimal("0.5"):
            return "not_tested_by_price"
        return "requires_regime_analysis"

    @staticmethod
    def _management_quality(
        exit_reason: ExitReason,
        mfe_r: Decimal,
        peak_pnl: Decimal,
        realised_pnl: Decimal,
    ) -> str:
        if exit_reason == ExitReason.STOP_LOSS and mfe_r >= Decimal("1"):
            return "breakeven_or_trailing_candidate"
        if peak_pnl > 0 and realised_pnl <= 0:
            return "profit_surrendered"
        if exit_reason in {ExitReason.TAKE_PROFIT, ExitReason.TRAILING_STOP}:
            return "protected"
        return "insufficient_favourable_excursion"

    @staticmethod
    def _diagnosis(
        exit_reason: ExitReason,
        direction: str,
        entry: str,
        stop: str,
        management: str,
    ) -> tuple[str, tuple[str, ...]]:
        factors = (f"direction:{direction}", f"entry:{entry}", f"stop:{stop}", f"management:{management}")
        if exit_reason == ExitReason.STOP_LOSS and management in {"profit_surrendered", "breakeven_or_trailing_candidate"}:
            return "profitable excursion was not protected", factors
        if exit_reason == ExitReason.STOP_LOSS and direction == "incorrect":
            return "signal direction or entry location failed", factors
        if exit_reason == ExitReason.STOP_LOSS:
            return "stop-out requires candle replay and structural context", factors
        if exit_reason == ExitReason.TAKE_PROFIT:
            return "target achieved", factors
        return "exit requires broker reconciliation", factors
