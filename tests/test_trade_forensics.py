from datetime import datetime, timedelta, timezone
from decimal import Decimal

from lilith.forensics.counterfactual import simulate_atr_trailing, simulate_breakeven
from lilith.forensics.models import (
    EntrySnapshot,
    ExitReason,
    LifecycleSnapshot,
    RealisedOutcome,
    Side,
)
from lilith.forensics.service import TradeForensicsService


def entry() -> EntrySnapshot:
    return EntrySnapshot(
        trade_id="T-1",
        signal_id="S-1",
        symbol="XAUUSDm",
        timeframe="M5",
        side=Side.BUY,
        timestamp=datetime(2026, 7, 28, 8, 0, tzinfo=timezone.utc),
        requested_entry=Decimal("100"),
        filled_entry=Decimal("100"),
        stop_price=Decimal("99"),
        target_price=Decimal("102"),
        volume=Decimal("0.01"),
        balance=Decimal("50"),
        equity=Decimal("50"),
    )


def snapshots() -> list[LifecycleSnapshot]:
    start = datetime(2026, 7, 28, 8, 0, tzinfo=timezone.utc)
    return [
        LifecycleSnapshot("T-1", start, Decimal("100.2"), Decimal("100.3"), floating_pnl=Decimal("0.2")),
        LifecycleSnapshot("T-1", start + timedelta(minutes=1), Decimal("101.2"), Decimal("101.3"), floating_pnl=Decimal("1.2")),
        LifecycleSnapshot("T-1", start + timedelta(minutes=2), Decimal("100.4"), Decimal("100.5"), floating_pnl=Decimal("0.4")),
        LifecycleSnapshot("T-1", start + timedelta(minutes=3), Decimal("99"), Decimal("99.1"), floating_pnl=Decimal("-1")),
    ]


def test_stop_out_after_positive_excursion_is_management_candidate() -> None:
    outcome = RealisedOutcome(
        trade_id="T-1",
        exit_timestamp=datetime(2026, 7, 28, 8, 3, tzinfo=timezone.utc),
        exit_price=Decimal("99"),
        gross_profit=Decimal("-1"),
        broker_reason="SL",
    )

    report = TradeForensicsService().analyse(entry(), snapshots(), outcome)

    assert report.exit_reason == ExitReason.STOP_LOSS
    assert report.mfe_r == Decimal("1.2")
    assert report.mae_r == Decimal("1")
    assert report.management_quality == "breakeven_or_trailing_candidate"
    assert report.primary_cause == "profitable excursion was not protected"
    assert report.net_realised_pnl == Decimal("-1")


def test_broker_costs_are_included_in_net_realised_pnl() -> None:
    outcome = RealisedOutcome(
        trade_id="T-1",
        exit_timestamp=datetime(2026, 7, 28, 8, 3, tzinfo=timezone.utc),
        exit_price=Decimal("102"),
        gross_profit=Decimal("2"),
        commission=Decimal("-0.10"),
        swap=Decimal("-0.02"),
        fee=Decimal("-0.03"),
        broker_reason="TP",
    )

    report = TradeForensicsService().analyse(entry(), snapshots()[:2], outcome)

    assert report.exit_reason == ExitReason.TAKE_PROFIT
    assert report.net_realised_pnl == Decimal("1.85")
    assert report.r_multiple == Decimal("2")


def test_breakeven_counterfactual_protects_trade_after_one_r() -> None:
    result = simulate_breakeven(entry(), snapshots(), activation_r=Decimal("1"))

    assert result.trigger_reached is True
    assert result.exit_price == Decimal("100")
    assert result.r_multiple == Decimal("0")


def test_atr_trailing_captures_part_of_favourable_move() -> None:
    result = simulate_atr_trailing(
        entry(),
        snapshots(),
        atr=Decimal("0.4"),
        multiplier=Decimal("1"),
        activation_r=Decimal("1"),
    )

    assert result.trigger_reached is True
    assert result.exit_price == Decimal("100.8")
    assert result.r_multiple == Decimal("0.8")
