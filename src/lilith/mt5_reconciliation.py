from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable

from .forensics.models import EntrySnapshot, LifecycleSnapshot, RealisedOutcome, Side
from .forensics.service import TradeForensicsService
from .sculpting import FeatureSculptor, TradeObservation


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"{path} line {number} must contain an object")
            rows.append(value)
    return rows


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str) + "\n")


def _replace_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":"), default=str) + "\n")
    tmp.replace(path)


def _dt(value: Any) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _decimal(value: Any) -> Decimal:
    return Decimal(str(value or 0))


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "value"):
        return value.value
    if isinstance(value, tuple):
        return list(value)
    return value


class MT5ForensicReconciler:
    """Converts complete Edith MT5 lifecycles into immutable research records."""

    ENTRY_CODES = {0}
    EXIT_CODES = {1, 2, 3}

    def __init__(self, data_dir: str | Path = "data") -> None:
        root = Path(data_dir)
        self.deals_path = root / "mt5_deals.jsonl"
        self.orders_path = root / "mt5_orders.jsonl"
        self.lifecycle_path = root / "mt5_position_snapshots.jsonl"
        self.forensics_path = root / "forensic_reports.jsonl"
        self.sculptor_path = root / "feature_sculptor_results.jsonl"
        self.service = TradeForensicsService()

    def reconcile(self) -> int:
        deals = _read_jsonl(self.deals_path)
        orders = _read_jsonl(self.orders_path)
        lifecycle = _read_jsonl(self.lifecycle_path)
        existing = _read_jsonl(self.forensics_path)
        completed = {str(row.get("trade_id")) for row in existing}
        grouped: dict[str, list[dict[str, Any]]] = {}
        for deal in deals:
            position_id = str(deal.get("position_id") or "")
            if position_id:
                grouped.setdefault(position_id, []).append(deal)

        added = 0
        for position_id, rows in grouped.items():
            if position_id in completed:
                continue
            rows.sort(key=lambda row: _dt(row["timestamp"]))
            entries = [row for row in rows if int(row.get("entry", -1)) in self.ENTRY_CODES]
            exits = [row for row in rows if int(row.get("entry", -1)) in self.EXIT_CODES]
            if not entries or not exits:
                continue
            entry_deal, exit_deal = entries[0], exits[-1]
            order = self._matching_order(entry_deal, orders)
            snapshots = [row for row in lifecycle if str(row.get("position_id")) == position_id]
            if order is None or not order.get("sl") or not order.get("tp"):
                continue
            side = Side(str(order.get("side", "BUY")).upper())
            entry = EntrySnapshot(
                trade_id=position_id,
                signal_id=str(order.get("signal_key") or order.get("order") or entry_deal.get("order")),
                symbol=str(entry_deal.get("symbol")), timeframe=str(order.get("timeframe") or "UNKNOWN"),
                side=side, timestamp=_dt(entry_deal["timestamp"]),
                requested_entry=_decimal(order.get("price")), filled_entry=_decimal(entry_deal.get("price")),
                stop_price=_decimal(order.get("sl")), target_price=_decimal(order.get("tp")),
                volume=_decimal(entry_deal.get("volume")), balance=_decimal(order.get("account_balance")),
                equity=_decimal(order.get("account_equity")), cash_risk=_decimal(order.get("projected_risk_cash")),
                raw_confidence=float(order.get("score") or 0), adjusted_confidence=float(order.get("score") or 0),
                session=self._session(_dt(entry_deal["timestamp"])), strategy_version="edith-mt5-demo-v1",
            )
            life = [LifecycleSnapshot(
                trade_id=position_id, timestamp=_dt(row["timestamp"]), bid=_decimal(row.get("bid")),
                ask=_decimal(row.get("ask")), stop_price=_decimal(row.get("sl")) if row.get("sl") else None,
                target_price=_decimal(row.get("tp")) if row.get("tp") else None,
                floating_pnl=_decimal(row.get("profit")),
            ) for row in snapshots]
            outcome = RealisedOutcome(
                trade_id=position_id, exit_timestamp=_dt(exit_deal["timestamp"]),
                exit_price=_decimal(exit_deal.get("price")), gross_profit=sum((_decimal(row.get("profit")) for row in exits), Decimal("0")),
                commission=sum((_decimal(row.get("commission")) for row in rows), Decimal("0")),
                swap=sum((_decimal(row.get("swap")) for row in rows), Decimal("0")),
                fee=sum((_decimal(row.get("fee")) for row in rows), Decimal("0")),
                broker_reason=str(exit_deal.get("reason") or exit_deal.get("comment") or ""),
            )
            report = self.service.analyse(entry, life, outcome)
            payload = {key: _jsonable(value) for key, value in asdict(report).items()}
            payload.update({
                "exit_timestamp": outcome.exit_timestamp.isoformat(), "entry_timestamp": entry.timestamp.isoformat(),
                "symbol": entry.symbol, "timeframe": entry.timeframe, "side": entry.side.value,
                "session": entry.session, "source": "mt5-demo", "position_id": position_id,
            })
            _append_jsonl(self.forensics_path, payload)
            existing.append(payload)
            completed.add(position_id)
            added += 1

        if added:
            self._refresh_sculptor(existing)
        return added

    @staticmethod
    def _matching_order(entry: dict[str, Any], orders: list[dict[str, Any]]) -> dict[str, Any] | None:
        candidates = [row for row in orders if row.get("status") == "accepted" and (
            str(row.get("deal")) == str(entry.get("ticket")) or str(row.get("order")) == str(entry.get("order"))
        )]
        return candidates[-1] if candidates else None

    @staticmethod
    def _session(timestamp: datetime) -> str:
        hour = timestamp.astimezone(timezone.utc).hour
        if 0 <= hour < 7:
            return "ASIA"
        if 7 <= hour < 13:
            return "LONDON"
        if 13 <= hour < 21:
            return "NEW_YORK"
        return "AFTER_HOURS"

    def _refresh_sculptor(self, reports: list[dict[str, Any]]) -> None:
        observations = [TradeObservation(
            trade_id=str(row["trade_id"]), net_pnl=_decimal(row.get("net_realised_pnl")),
            r_multiple=_decimal(row.get("r_multiple")), features={
                "symbol": str(row.get("symbol", "UNKNOWN")), "timeframe": str(row.get("timeframe", "UNKNOWN")),
                "side": str(row.get("side", "UNKNOWN")), "session": str(row.get("session", "UNKNOWN")),
                "exit_reason": str(row.get("exit_reason", "UNKNOWN")),
                "management_quality": str(row.get("management_quality", "UNKNOWN")),
            },
        ) for row in reports]
        results = FeatureSculptor().analyse(observations)
        _replace_jsonl(self.sculptor_path, [
            {key: _jsonable(value) for key, value in asdict(result).items()} for result in results
        ])
