from __future__ import annotations

import pandas as pd

from .engine import _prepare
from .models import AMDStructureConfig, AMDStructureSignal, BacktestTrade, Direction, Outcome


class AMDStructureBacktester:
    """Conservative bar backtester: stop wins ties when stop and target occur in one bar."""

    def __init__(self, config: AMDStructureConfig | None = None) -> None:
        self.config = config or AMDStructureConfig()

    def evaluate(self, candles: pd.DataFrame, signals: list[AMDStructureSignal]) -> list[BacktestTrade]:
        frame = _prepare(candles, self.config.timezone)
        trades: list[BacktestTrade] = []
        for signal in signals:
            start = pd.Timestamp(signal.bos_time)
            if start.tzinfo is None:
                start = start.tz_localize(self.config.timezone)
            day = frame[(frame["timestamp"] >= start) & (frame["timestamp"].dt.date.astype(str) == signal.session_date)]
            fill_index: int | None = None
            for idx, row in day.iterrows():
                if float(row["low"]) <= signal.entry_price <= float(row["high"]):
                    fill_index = idx
                    break
            if fill_index is None:
                trades.append(BacktestTrade(signal, None, None, Outcome.NO_FILL, 0.0, 0, 0.0, 0.0))
                continue
            after = frame.loc[fill_index:]
            after = after[after["timestamp"].dt.date.astype(str) == signal.session_date]
            risk = abs(signal.entry_price - signal.stop_price)
            mfe = mae = 0.0
            outcome = Outcome.EXPIRED
            exit_time: str | None = None
            realised = 0.0
            bars = 0
            for bars, (_, row) in enumerate(after.iterrows(), start=1):
                high, low = float(row["high"]), float(row["low"])
                if signal.direction is Direction.BULLISH:
                    mfe = max(mfe, (high - signal.entry_price) / risk)
                    mae = min(mae, (low - signal.entry_price) / risk)
                    stopped, targeted = low <= signal.stop_price, high >= signal.target_price
                else:
                    mfe = max(mfe, (signal.entry_price - low) / risk)
                    mae = min(mae, (signal.entry_price - high) / risk)
                    stopped, targeted = high >= signal.stop_price, low <= signal.target_price
                if stopped:
                    outcome, realised, exit_time = Outcome.LOSS, -1.0, row["timestamp"].isoformat()
                    break
                if targeted:
                    outcome, realised, exit_time = Outcome.WIN, signal.target_r, row["timestamp"].isoformat()
                    break
            trades.append(BacktestTrade(
                signal=signal,
                entry_time=frame.loc[fill_index, "timestamp"].isoformat(),
                exit_time=exit_time,
                outcome=outcome,
                realised_r=realised,
                bars_held=bars,
                maximum_favourable_r=round(mfe, 4),
                maximum_adverse_r=round(mae, 4),
            ))
        return trades


def summarize(trades: list[BacktestTrade]) -> dict[str, float | int]:
    resolved = [trade for trade in trades if trade.outcome in {Outcome.WIN, Outcome.LOSS}]
    wins = sum(trade.outcome is Outcome.WIN for trade in resolved)
    total_r = sum(trade.realised_r for trade in resolved)
    return {
        "signals": len(trades),
        "filled": sum(trade.outcome is not Outcome.NO_FILL for trade in trades),
        "resolved": len(resolved),
        "wins": wins,
        "losses": len(resolved) - wins,
        "win_rate": round(wins / len(resolved), 4) if resolved else 0.0,
        "expectancy_r": round(total_r / len(resolved), 4) if resolved else 0.0,
        "net_r": round(total_r, 4),
    }
