from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable

from .models import EntrySnapshot, LifecycleSnapshot, Side


@dataclass(frozen=True, slots=True)
class CounterfactualResult:
    policy: str
    exit_price: Decimal
    r_multiple: Decimal
    trigger_reached: bool


def simulate_breakeven(
    entry: EntrySnapshot,
    lifecycle: Iterable[LifecycleSnapshot],
    activation_r: Decimal = Decimal("1"),
) -> CounterfactualResult:
    risk = entry.initial_risk_distance
    activation = risk * activation_r
    armed = False

    for snapshot in sorted(lifecycle, key=lambda item: item.timestamp):
        price = snapshot.bid if entry.side == Side.BUY else snapshot.ask
        favourable = price - entry.filled_entry if entry.side == Side.BUY else entry.filled_entry - price
        if favourable >= activation:
            armed = True
        if armed:
            breached = price <= entry.filled_entry if entry.side == Side.BUY else price >= entry.filled_entry
            if breached:
                return CounterfactualResult(
                    policy=f"breakeven_at_{activation_r}R",
                    exit_price=entry.filled_entry,
                    r_multiple=Decimal("0"),
                    trigger_reached=True,
                )

    final_price = _last_mark(entry, lifecycle)
    return CounterfactualResult(
        policy=f"breakeven_at_{activation_r}R",
        exit_price=final_price,
        r_multiple=_r_multiple(entry, final_price),
        trigger_reached=armed,
    )


def simulate_atr_trailing(
    entry: EntrySnapshot,
    lifecycle: Iterable[LifecycleSnapshot],
    atr: Decimal,
    multiplier: Decimal = Decimal("1.5"),
    activation_r: Decimal = Decimal("1"),
) -> CounterfactualResult:
    if atr <= 0 or multiplier <= 0:
        raise ValueError("atr and multiplier must be positive")

    snapshots = sorted(lifecycle, key=lambda item: item.timestamp)
    risk = entry.initial_risk_distance
    activation = risk * activation_r
    trailing_stop: Decimal | None = None
    armed = False

    for snapshot in snapshots:
        price = snapshot.bid if entry.side == Side.BUY else snapshot.ask
        favourable = price - entry.filled_entry if entry.side == Side.BUY else entry.filled_entry - price
        if favourable >= activation:
            armed = True
        if not armed:
            continue

        candidate = price - atr * multiplier if entry.side == Side.BUY else price + atr * multiplier
        if trailing_stop is None:
            trailing_stop = candidate
        elif entry.side == Side.BUY:
            trailing_stop = max(trailing_stop, candidate)
        else:
            trailing_stop = min(trailing_stop, candidate)

        breached = price <= trailing_stop if entry.side == Side.BUY else price >= trailing_stop
        if breached:
            return CounterfactualResult(
                policy=f"atr_trailing_{multiplier}x_atr_after_{activation_r}R",
                exit_price=trailing_stop,
                r_multiple=_r_multiple(entry, trailing_stop),
                trigger_reached=True,
            )

    final_price = _last_mark(entry, snapshots)
    return CounterfactualResult(
        policy=f"atr_trailing_{multiplier}x_atr_after_{activation_r}R",
        exit_price=final_price,
        r_multiple=_r_multiple(entry, final_price),
        trigger_reached=armed,
    )


def _last_mark(entry: EntrySnapshot, lifecycle: Iterable[LifecycleSnapshot]) -> Decimal:
    snapshots = list(lifecycle)
    if not snapshots:
        return entry.filled_entry
    last = snapshots[-1]
    return last.bid if entry.side == Side.BUY else last.ask


def _r_multiple(entry: EntrySnapshot, price: Decimal) -> Decimal:
    move = price - entry.filled_entry if entry.side == Side.BUY else entry.filled_entry - price
    return move / entry.initial_risk_distance
