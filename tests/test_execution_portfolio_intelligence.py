from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from lilith.forensics.models import EntrySnapshot, LifecycleSnapshot, RealisedOutcome, Side
from lilith.intelligence import ExecutionIntelligenceEngine, PortfolioIntelligenceEngine, PortfolioTrade


def entry() -> EntrySnapshot:
    return EntrySnapshot(
        trade_id="trade-1",
        signal_id="signal-1",
        symbol="XAUUSDm",
        timeframe="5m",
        side=Side.BUY,
        timestamp=datetime(2026, 7, 31, 8, 0, tzinfo=timezone.utc),
        requested_entry=Decimal("3300.0"),
        filled_entry=Decimal("3300.1"),
        stop_price=Decimal("3299.1"),
        target_price=Decimal("3302.1"),
        volume=Decimal("0.01"),
        balance=Decimal("1000"),
        equity=Decimal("1000"),
        spread=Decimal("0.05"),
        slippage=Decimal("0.10"),
        cash_risk=Decimal("10"),
        risk_percent=Decimal("1"),
        session="LONDON",
        regime="TRENDING",
        structure="BULLISH",
        raw_confidence=0.80,
        adjusted_confidence=0.78,
        entry_quality_score=0.85,
    )


def lifecycle() -> list[LifecycleSnapshot]:
    start = datetime(2026, 7, 31, 8, 0, tzinfo=timezone.utc)
    prices = [3300.0, 3300.5, 3301.0, 3301.8, 3301.2]
    return [
        LifecycleSnapshot(
            trade_id="trade-1",
            timestamp=start + timedelta(minutes=index * 5),
            bid=Decimal(str(price)),
            ask=Decimal(str(price + 0.05)),
            floating_pnl=Decimal("0"),
        )
        for index, price in enumerate(prices)
    ]


def test_execution_intelligence_scores_completed_trade():
    report = ExecutionIntelligenceEngine().analyse(
        entry(),
        lifecycle(),
        RealisedOutcome(
            trade_id="trade-1",
            exit_timestamp=datetime(2026, 7, 31, 8, 25, tzinfo=timezone.utc),
            exit_price=Decimal("3301.1"),
            gross_profit=Decimal("10"),
        ),
    )
    assert report.realised_r == pytest.approx(1.0)
    assert report.mfe_r == pytest.approx(1.7)
    assert report.premature_exit is False
    assert 0.0 <= report.institutional_execution_index <= 1.0
    assert report.execution_grade in {"A+", "A", "B", "C", "D", "F"}
    assert report.time_in_profit_seconds > 0


def test_execution_intelligence_detects_premature_exit():
    report = ExecutionIntelligenceEngine().analyse(
        entry(),
        lifecycle(),
        RealisedOutcome(
            trade_id="trade-1",
            exit_timestamp=datetime(2026, 7, 31, 8, 25, tzinfo=timezone.utc),
            exit_price=Decimal("3300.5"),
            gross_profit=Decimal("4"),
        ),
    )
    assert report.premature_exit is True
    assert "premature_exit" in report.reasons


def test_execution_intelligence_rejects_mismatched_trade_ids():
    with pytest.raises(ValueError, match="trade IDs"):
        ExecutionIntelligenceEngine().analyse(
            entry(),
            lifecycle(),
            RealisedOutcome(
                trade_id="other",
                exit_timestamp=datetime(2026, 7, 31, 8, 25, tzinfo=timezone.utc),
                exit_price=Decimal("3301"),
                gross_profit=Decimal("1"),
            ),
        )


def portfolio_trades() -> list[PortfolioTrade]:
    returns = [1.0, -0.5, 1.2, 0.8, -0.4, 1.5, -0.3, 0.7, 1.1, -0.2]
    trades = []
    equity = 1000.0
    for index, r_value in enumerate(returns):
        pnl = r_value * 10.0
        trades.append(
            PortfolioTrade(
                trade_id=f"trade-{index}",
                timestamp_utc=f"2026-07-31T{index:02d}:00:00+00:00",
                instrument="XAUUSDm" if index % 2 else "EURUSD",
                timeframe="5m" if index % 3 else "15m",
                session="LONDON" if index % 2 else "NEW_YORK",
                strategy="edith-observation-a" if index % 2 else "edith-observation-b",
                side="BUY" if index % 2 else "SELL",
                realised_pnl=pnl,
                r_multiple=r_value,
                cash_risk=10.0,
                equity_before=equity,
            )
        )
        equity += pnl
    return trades


def test_portfolio_intelligence_calculates_risk_and_health():
    report = PortfolioIntelligenceEngine().analyse(portfolio_trades())
    assert report.sample_size == 10
    assert report.total_pnl > 0
    assert report.expectancy_r > 0
    assert report.maximum_drawdown >= 0
    assert report.expected_shortfall_95_r >= report.value_at_risk_95_r
    assert 0.0 <= report.risk_of_ruin_proxy <= 1.0
    assert 0.0 <= report.portfolio_health_score <= 1.0
    assert 0.0 <= report.concentration.diversification_score <= 1.0


def test_portfolio_intelligence_flags_concentration_and_negative_edge():
    trades = [
        PortfolioTrade(
            trade_id=f"loss-{index}",
            timestamp_utc=f"2026-07-31T{index:02d}:00:00+00:00",
            instrument="XAUUSDm",
            timeframe="5m",
            session="LONDON",
            strategy="one-strategy",
            side="BUY",
            realised_pnl=-20.0,
            r_multiple=-1.0,
            cash_risk=20.0,
            equity_before=1000.0 - index * 20,
        )
        for index in range(8)
    ]
    report = PortfolioIntelligenceEngine().analyse(trades)
    assert "high_concentration" in report.warnings
    assert "non_positive_expectancy" in report.warnings
    assert report.concentration.maximum_bucket_share == pytest.approx(1.0)


def test_portfolio_requires_evidence():
    with pytest.raises(ValueError, match="at least one"):
        PortfolioIntelligenceEngine().analyse([])
