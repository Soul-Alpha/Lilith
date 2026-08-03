from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
import json

import pytest

from lilith.intelligence import (
    CashFlowEvent,
    ClosedRiskTrade,
    DailyRiskFileService,
    DailyRiskLedgerEngine,
    DailyRiskPolicy,
    OpenRiskPosition,
)


DAY = date(2026, 8, 3)


def instant(hour: int) -> datetime:
    return datetime(2026, 8, 3, hour, tzinfo=timezone.utc)


def policy() -> DailyRiskPolicy:
    return DailyRiskPolicy(
        daily_budget_cash=Decimal("100"),
        daily_budget_r=Decimal("2"),
        currency="USD",
    )


def test_losses_and_open_risk_consume_budget_but_wins_do_not_restore_it() -> None:
    snapshot = DailyRiskLedgerEngine().build(
        trading_date=DAY,
        policy=policy(),
        closed_trades=[
            ClosedRiskTrade("win", instant(9), Decimal("30"), Decimal("1.5"), "forensic:win"),
            ClosedRiskTrade("loss", instant(10), Decimal("-20"), Decimal("-1"), "forensic:loss"),
        ],
        open_positions=[
            OpenRiskPosition(
                "open-1", instant(11), Decimal("25"), Decimal("0.5"), Decimal("4"), ("position:open-1",)
            )
        ],
        generated_at=instant(12),
    )

    assert snapshot.realised_net_pnl_cash == Decimal("10")
    assert snapshot.realised_profit_cash == Decimal("30")
    assert snapshot.realised_loss_cash == Decimal("20")
    assert snapshot.consumed_risk_cash == Decimal("45")
    assert snapshot.remaining_risk_cash == Decimal("55")
    assert snapshot.consumed_risk_r == Decimal("1.5")
    assert snapshot.remaining_risk_r == Decimal("0.5")
    assert snapshot.consecutive_losses == 1
    assert snapshot.advisory_only is True


def test_external_cash_flows_are_reported_but_excluded_from_trading_pnl() -> None:
    snapshot = DailyRiskLedgerEngine().build(
        trading_date=DAY,
        policy=policy(),
        closed_trades=[
            ClosedRiskTrade("trade", instant(9), Decimal("-10"), Decimal("-0.5"), "forensic:trade")
        ],
        cash_flows=[
            CashFlowEvent("deposit", instant(8), Decimal("500"), "deposit"),
            CashFlowEvent("withdrawal", instant(10), Decimal("-100"), "withdrawal"),
        ],
        generated_at=instant(12),
    )

    assert snapshot.realised_net_pnl_cash == Decimal("-10")
    assert snapshot.excluded_cash_flow_cash == Decimal("400")
    assert snapshot.consumed_risk_cash == Decimal("10")


def test_unknown_open_risk_prevents_available_budget_claim() -> None:
    snapshot = DailyRiskLedgerEngine().build(
        trading_date=DAY,
        policy=policy(),
        open_positions=[
            OpenRiskPosition("unknown", instant(11), None, None, Decimal("2"), ("position:unknown",))
        ],
        generated_at=instant(12),
    )

    assert snapshot.evidence_complete is False
    assert snapshot.open_risk_cash is None
    assert snapshot.consumed_risk_cash is None
    assert snapshot.remaining_risk_cash is None
    assert "missing_open_cash_risk:unknown" in snapshot.evidence_reasons


def test_conflicting_duplicate_trade_is_rejected() -> None:
    with pytest.raises(ValueError, match="conflicting closed trade"):
        DailyRiskLedgerEngine().build(
            trading_date=DAY,
            policy=policy(),
            closed_trades=[
                ClosedRiskTrade("same", instant(9), Decimal("10"), Decimal("1"), "source:a"),
                ClosedRiskTrade("same", instant(9), Decimal("-10"), Decimal("-1"), "source:b"),
            ],
            generated_at=instant(12),
        )


def write_jsonl(path, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def test_file_service_reconciles_partial_position_and_preserves_history(tmp_path) -> None:
    write_jsonl(
        tmp_path / "forensic_reports.jsonl",
        [{
            "trade_id": "closed-1",
            "exit_timestamp": instant(9).isoformat(),
            "net_realised_pnl": "-15",
            "r_multiple": "-0.75",
        }],
    )
    write_jsonl(
        tmp_path / "mt5_deals.jsonl",
        [
            {
                "timestamp": instant(8).isoformat(), "ticket": 100, "order": 200,
                "position_id": 300, "entry": 0, "volume": 0.02,
            },
            {
                "timestamp": instant(10).isoformat(), "ticket": 101, "order": 201,
                "position_id": 300, "entry": 1, "volume": 0.01,
            },
        ],
    )
    write_jsonl(
        tmp_path / "mt5_orders.jsonl",
        [{
            "timestamp": instant(8).isoformat(), "status": "accepted", "order": 200,
            "deal": 100, "projected_risk_cash": 10,
        }],
    )
    write_jsonl(
        tmp_path / "mt5_position_snapshots.jsonl",
        [{
            "timestamp": instant(11).isoformat(), "position_id": 300, "volume": 0.01, "profit": 3,
        }],
    )

    service = DailyRiskFileService(tmp_path)
    first = service.refresh(policy(), trading_date=DAY, generated_at=instant(12))
    second = service.refresh(policy(), trading_date=DAY, generated_at=instant(13))

    assert first.open_position_count == 1
    assert first.open_risk_cash == Decimal("5")
    assert first.open_risk_r == Decimal("0.5")
    assert first.consumed_risk_cash == Decimal("20")
    assert first.report_id == second.report_id
    history = (tmp_path / "portfolio" / "daily_risk_snapshots.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(history) == 1
    latest = json.loads((tmp_path / "portfolio" / "latest_daily_risk.json").read_text(encoding="utf-8"))
    assert latest["report_id"] == first.report_id


def test_missing_telemetry_files_produce_awaiting_evidence(tmp_path) -> None:
    snapshot = DailyRiskFileService(tmp_path).refresh(
        policy(), trading_date=DAY, generated_at=instant(12)
    )
    assert snapshot.evidence_complete is False
    assert any(reason.startswith("missing_source_file:") for reason in snapshot.evidence_reasons)
