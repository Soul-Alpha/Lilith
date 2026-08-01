from __future__ import annotations

import hashlib
from dataclasses import dataclass

import pandas as pd

from .models import AMDStructureConfig, AMDStructureSignal, Direction, EntryZone

_REQUIRED = {"timestamp", "open", "high", "low", "close"}


@dataclass(frozen=True)
class _Break:
    index: int
    level: float


def _prepare(candles: pd.DataFrame, timezone: str) -> pd.DataFrame:
    missing = _REQUIRED.difference(candles.columns)
    if missing:
        raise ValueError(f"Missing candle columns: {sorted(missing)}")
    frame = candles.copy()
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="raise").dt.tz_convert(timezone)
    frame = frame.sort_values("timestamp").drop_duplicates("timestamp", keep="last").reset_index(drop=True)
    for column in ("open", "high", "low", "close"):
        frame[column] = pd.to_numeric(frame[column], errors="raise")
    if ((frame["high"] < frame[["open", "close"]].max(axis=1)) | (frame["low"] > frame[["open", "close"]].min(axis=1))).any():
        raise ValueError("Invalid OHLC candle")
    prior_close = frame["close"].shift(1)
    true_range = pd.concat(
        [frame["high"] - frame["low"], (frame["high"] - prior_close).abs(), (frame["low"] - prior_close).abs()],
        axis=1,
    ).max(axis=1)
    frame["atr"] = true_range.rolling(14, min_periods=5).mean().bfill()
    return frame


def _session(frame: pd.DataFrame, start, end) -> pd.DataFrame:
    clock = frame["timestamp"].dt.time
    return frame[(clock >= start) & (clock < end)]


def _recent_swing_high(frame: pd.DataFrame, upto: int, window: int) -> float | None:
    start = max(0, upto - max(5, window * 4))
    values = frame.iloc[start:upto]["high"]
    return float(values.max()) if not values.empty else None


def _recent_swing_low(frame: pd.DataFrame, upto: int, window: int) -> float | None:
    start = max(0, upto - max(5, window * 4))
    values = frame.iloc[start:upto]["low"]
    return float(values.min()) if not values.empty else None


def _find_breaks(post_sweep: pd.DataFrame, direction: Direction, config: AMDStructureConfig) -> tuple[_Break, _Break] | None:
    choch: _Break | None = None
    for local_index in range(2, len(post_sweep)):
        row = post_sweep.iloc[local_index]
        atr = max(float(row["atr"]), 1e-9)
        body = abs(float(row["close"] - row["open"]))
        if direction is Direction.BULLISH:
            minor = _recent_swing_high(post_sweep, local_index, config.swing_window)
            broken = minor is not None and float(row["close"]) > minor
        else:
            minor = _recent_swing_low(post_sweep, local_index, config.swing_window)
            broken = minor is not None and float(row["close"]) < minor
        if broken and choch is None:
            choch = _Break(local_index, float(minor))
            continue
        if broken and choch is not None and local_index > choch.index and body / atr >= config.displacement_body_atr:
            return choch, _Break(local_index, float(minor))
    return None


def _entry_zone(frame: pd.DataFrame, bos_index: int, direction: Direction) -> EntryZone | None:
    bos = frame.iloc[bos_index]
    search = frame.iloc[max(0, bos_index - 6):bos_index]
    if direction is Direction.BULLISH:
        candidates = search[search["close"] < search["open"]]
        if candidates.empty or bos_index < 2:
            return None
        ob = candidates.iloc[-1]
        fvg_lower = float(frame.iloc[bos_index - 2]["high"])
        fvg_upper = float(bos["low"])
    else:
        candidates = search[search["close"] > search["open"]]
        if candidates.empty or bos_index < 2:
            return None
        ob = candidates.iloc[-1]
        fvg_lower = float(bos["high"])
        fvg_upper = float(frame.iloc[bos_index - 2]["low"])
    if fvg_upper <= fvg_lower:
        return None
    ob_lower, ob_upper = float(ob["low"]), float(ob["high"])
    lower, upper = max(ob_lower, fvg_lower), min(ob_upper, fvg_upper)
    if upper <= lower:
        return None
    return EntryZone(lower, upper, ob_lower, ob_upper, fvg_lower, fvg_upper)


class AMDStructureEngine:
    """Jaxter research engine. It emits evidence only and has no execution dependency."""

    def __init__(self, config: AMDStructureConfig | None = None) -> None:
        self.config = config or AMDStructureConfig()

    def scan(self, candles: pd.DataFrame, *, symbol: str = "XAUUSD", timeframe: str = "M5") -> list[AMDStructureSignal]:
        frame = _prepare(candles, self.config.timezone)
        signals: list[AMDStructureSignal] = []
        for session_date, day in frame.groupby(frame["timestamp"].dt.date, sort=True):
            asian = _session(day, self.config.asian_start, self.config.asian_end)
            london = _session(day, self.config.london_start, self.config.london_end).head(self.config.max_manipulation_bars)
            distribution = _session(day, self.config.london_start, self.config.distribution_end)
            if len(asian) < 4 or len(london) < 2 or len(distribution) < 5:
                continue
            asian_high, asian_low = float(asian["high"].max()), float(asian["low"].min())
            candidates: list[tuple[int, Direction, float]] = []
            for idx, row in london.iterrows():
                atr = max(float(row["atr"]), 1e-9)
                lower_wick = min(float(row["open"]), float(row["close"])) - float(row["low"])
                upper_wick = float(row["high"]) - max(float(row["open"]), float(row["close"]))
                if float(row["low"]) < asian_low and float(row["close"]) > asian_low and lower_wick / atr >= self.config.sharp_wick_atr:
                    candidates.append((idx, Direction.BULLISH, float(row["low"])))
                if float(row["high"]) > asian_high and float(row["close"]) < asian_high and upper_wick / atr >= self.config.sharp_wick_atr:
                    candidates.append((idx, Direction.BEARISH, float(row["high"])))
            if not candidates:
                continue
            sweep_index, direction, sweep_price = candidates[0]
            post = distribution.loc[sweep_index:].reset_index()
            breaks = _find_breaks(post, direction, self.config)
            if breaks is None:
                continue
            choch, bos = breaks
            zone = _entry_zone(post, bos.index, direction)
            if zone is None:
                continue
            bos_row, sweep_row = post.iloc[bos.index], day.loc[sweep_index]
            atr = max(float(bos_row["atr"]), 1e-9)
            entry = (zone.lower + zone.upper) / 2
            if direction is Direction.BULLISH:
                stop = sweep_price - atr * self.config.stop_buffer_atr
                target = entry + (entry - stop) * self.config.target_r
            else:
                stop = sweep_price + atr * self.config.stop_buffer_atr
                target = entry - (stop - entry) * self.config.target_r
            risk = abs(entry - stop)
            if risk <= 0:
                continue
            quality = min(100.0, 35.0 + min(25.0, abs(float(sweep_row["close"]) - sweep_price) / atr * 20) + min(30.0, abs(float(bos_row["close"] - bos_row["open"])) / atr * 25) + 10.0)
            raw_id = f"{self.config.strategy_version}|{symbol}|{timeframe}|{session_date}|{direction.value}|{sweep_price:.8f}|{entry:.8f}"
            signals.append(AMDStructureSignal(
                signal_id=hashlib.sha256(raw_id.encode()).hexdigest()[:24], session_date=str(session_date), symbol=symbol,
                timeframe=timeframe, direction=direction, asian_high=asian_high, asian_low=asian_low,
                sweep_price=sweep_price, sweep_time=sweep_row["timestamp"].isoformat(),
                choch_time=post.iloc[choch.index]["timestamp"].isoformat(), bos_time=bos_row["timestamp"].isoformat(),
                entry_zone=zone, entry_price=entry, stop_price=stop, target_price=target,
                target_r=self.config.target_r, quality_score=round(quality, 2),
                reasons=("asian_range_mapped", "sharp_london_liquidity_sweep", "choch_observed", "displacement_bos_confirmed", "order_block_fvg_overlap"),
                strategy_version=self.config.strategy_version,
            ))
            if self.config.one_trade_per_session:
                continue
        return signals
