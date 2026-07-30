from __future__ import annotations

import json
from pathlib import Path

from lilith.mt5_reconciliation import MT5ForensicReconciler


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def test_reconciles_complete_position_and_is_idempotent(tmp_path: Path) -> None:
    write_jsonl(tmp_path / "mt5_orders.jsonl", [{
        "timestamp": "2026-07-30T07:00:00+00:00", "status": "accepted", "side": "BUY",
        "symbol": "XAUUSDm", "order": 11, "deal": 101, "price": 100.0,
        "sl": 99.0, "tp": 102.0, "volume": 0.01, "projected_risk_cash": 1.0,
    }])
    write_jsonl(tmp_path / "mt5_deals.jsonl", [
        {"timestamp": "2026-07-30T07:00:01+00:00", "ticket": 101, "order": 11,
         "position_id": 9001, "symbol": "XAUUSDm", "entry": 0, "volume": 0.01,
         "price": 100.0, "profit": 0.0, "commission": -0.05, "swap": 0.0, "fee": 0.0},
        {"timestamp": "2026-07-30T07:10:00+00:00", "ticket": 102, "order": 12,
         "position_id": 9001, "symbol": "XAUUSDm", "entry": 1, "volume": 0.01,
         "price": 102.0, "profit": 2.0, "commission": -0.05, "swap": 0.0, "fee": 0.0,
         "comment": "tp"},
    ])
    write_jsonl(tmp_path / "mt5_position_snapshots.jsonl", [{
        "timestamp": "2026-07-30T07:05:00+00:00", "position_id": 9001,
        "bid": 101.0, "ask": 101.1, "sl": 99.0, "tp": 102.0, "profit": 1.0,
    }])

    reconciler = MT5ForensicReconciler(tmp_path)
    assert reconciler.reconcile() == 1
    assert reconciler.reconcile() == 0

    reports = [json.loads(line) for line in (tmp_path / "forensic_reports.jsonl").read_text().splitlines()]
    assert len(reports) == 1
    assert reports[0]["trade_id"] == "9001"
    assert reports[0]["exit_reason"] == "TAKE_PROFIT"
    assert reports[0]["net_realised_pnl"] == "1.90"
    assert reports[0]["r_multiple"] == "2"
    assert (tmp_path / "feature_sculptor_results.jsonl").exists()


def test_incomplete_position_is_not_promoted(tmp_path: Path) -> None:
    write_jsonl(tmp_path / "mt5_deals.jsonl", [{
        "timestamp": "2026-07-30T07:00:01+00:00", "ticket": 101, "order": 11,
        "position_id": 9001, "symbol": "XAUUSDm", "entry": 0, "volume": 0.01,
        "price": 100.0, "profit": 0.0, "commission": 0.0, "swap": 0.0, "fee": 0.0,
    }])
    assert MT5ForensicReconciler(tmp_path).reconcile() == 0
    assert not (tmp_path / "forensic_reports.jsonl").exists()
