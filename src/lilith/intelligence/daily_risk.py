from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable


_ZERO = Decimal("0")
_ENTRY_CODES = {0}
_EXIT_CODES = {1, 2, 3}


def _decimal(value: Any) -> Decimal:
    if value is None or value == "":
        return _ZERO
    return Decimal(str(value))


def _optional_decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    return Decimal(str(value))


def _timestamp(value: Any) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, tuple):
        return list(value)
    raise TypeError(f"unsupported daily-risk value: {type(value)!r}")


def _canonical_hash(payload: Any) -> str:
    encoded = json.dumps(payload, default=_json_default, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"{path} line {number} must contain a JSON object")
            rows.append(value)
    return rows


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, default=_json_default, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    temporary.replace(path)


@dataclass(frozen=True, slots=True)
class DailyRiskPolicy:
    daily_budget_cash: Decimal
    daily_budget_r: Decimal = Decimal("2")
    currency: str = "USD"
    policy_version: str = "edith-daily-risk-v1"

    def __post_init__(self) -> None:
        if self.daily_budget_cash <= 0:
            raise ValueError("daily_budget_cash must be positive")
        if self.daily_budget_r <= 0:
            raise ValueError("daily_budget_r must be positive")
        if not self.currency.strip():
            raise ValueError("currency is required")


@dataclass(frozen=True, slots=True)
class ClosedRiskTrade:
    trade_id: str
    exit_timestamp: datetime
    net_realised_pnl: Decimal
    realised_r: Decimal
    source_record_id: str

    def __post_init__(self) -> None:
        if self.exit_timestamp.tzinfo is None:
            raise ValueError("exit_timestamp must be timezone-aware")
        if not self.trade_id or not self.source_record_id:
            raise ValueError("trade and source identifiers are required")


@dataclass(frozen=True, slots=True)
class OpenRiskPosition:
    position_id: str
    snapshot_timestamp: datetime | None
    projected_risk_cash: Decimal | None
    projected_risk_r: Decimal | None
    floating_pnl: Decimal
    source_record_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.snapshot_timestamp is not None and self.snapshot_timestamp.tzinfo is None:
            raise ValueError("snapshot_timestamp must be timezone-aware")
        if self.projected_risk_cash is not None and self.projected_risk_cash < 0:
            raise ValueError("projected_risk_cash cannot be negative")
        if self.projected_risk_r is not None and self.projected_risk_r < 0:
            raise ValueError("projected_risk_r cannot be negative")
        if not self.position_id:
            raise ValueError("position_id is required")


@dataclass(frozen=True, slots=True)
class CashFlowEvent:
    event_id: str
    timestamp: datetime
    amount: Decimal
    category: str

    def __post_init__(self) -> None:
        if self.timestamp.tzinfo is None:
            raise ValueError("cash-flow timestamp must be timezone-aware")
        if not self.event_id:
            raise ValueError("cash-flow event_id is required")


@dataclass(frozen=True, slots=True)
class DailyRiskSnapshot:
    report_id: str
    schema_version: str
    policy_version: str
    trading_date: str
    currency: str
    daily_budget_cash: Decimal
    daily_budget_r: Decimal
    realised_net_pnl_cash: Decimal
    realised_profit_cash: Decimal
    realised_loss_cash: Decimal
    realised_loss_r: Decimal
    open_risk_cash: Decimal | None
    open_risk_r: Decimal | None
    open_floating_pnl_cash: Decimal
    consumed_risk_cash: Decimal | None
    consumed_risk_r: Decimal | None
    remaining_risk_cash: Decimal | None
    remaining_risk_r: Decimal | None
    open_portfolio_heat_r: Decimal | None
    trade_count: int
    open_position_count: int
    consecutive_losses: int
    excluded_cash_flow_cash: Decimal
    evidence_complete: bool
    evidence_reasons: tuple[str, ...]
    source_record_ids: tuple[str, ...]
    configuration_hash: str
    generated_at_utc: datetime
    advisory_only: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class DailyRiskLedgerEngine:
    """Builds an advisory daily risk ledger without changing execution state."""

    schema_version = "edith-daily-risk-snapshot-v1"

    def build(
        self,
        *,
        trading_date: date,
        policy: DailyRiskPolicy,
        closed_trades: Iterable[ClosedRiskTrade] = (),
        open_positions: Iterable[OpenRiskPosition] = (),
        cash_flows: Iterable[CashFlowEvent] = (),
        generated_at: datetime | None = None,
        additional_reasons: Iterable[str] = (),
    ) -> DailyRiskSnapshot:
        generated = generated_at or datetime.now(timezone.utc)
        if generated.tzinfo is None:
            raise ValueError("generated_at must be timezone-aware")
        generated = generated.astimezone(timezone.utc)

        closed = self._unique_closed(closed_trades)
        open_items = self._unique_open(open_positions)
        flows = self._unique_flows(cash_flows)

        closed = [item for item in closed if item.exit_timestamp.astimezone(timezone.utc).date() == trading_date]
        flows = [item for item in flows if item.timestamp.astimezone(timezone.utc).date() == trading_date]

        realised_net = sum((item.net_realised_pnl for item in closed), _ZERO)
        realised_profit = sum((item.net_realised_pnl for item in closed if item.net_realised_pnl > 0), _ZERO)
        realised_loss = sum((-item.net_realised_pnl for item in closed if item.net_realised_pnl < 0), _ZERO)
        realised_loss_r = sum((-item.realised_r for item in closed if item.realised_r < 0), _ZERO)
        excluded_cash_flow = sum((item.amount for item in flows), _ZERO)
        floating = sum((item.floating_pnl for item in open_items), _ZERO)

        reasons = sorted(set(str(reason) for reason in additional_reasons if str(reason)))
        missing_cash = [item.position_id for item in open_items if item.projected_risk_cash is None]
        missing_r = [item.position_id for item in open_items if item.projected_risk_r is None]
        if missing_cash:
            reasons.append(f"missing_open_cash_risk:{','.join(sorted(missing_cash))}")
        if missing_r:
            reasons.append(f"missing_open_r_risk:{','.join(sorted(missing_r))}")

        open_cash = None if missing_cash else sum((item.projected_risk_cash or _ZERO for item in open_items), _ZERO)
        open_r = None if missing_r else sum((item.projected_risk_r or _ZERO for item in open_items), _ZERO)
        consumed_cash = None if open_cash is None else realised_loss + open_cash
        consumed_r = None if open_r is None else realised_loss_r + open_r
        remaining_cash = None if consumed_cash is None else max(policy.daily_budget_cash - consumed_cash, _ZERO)
        remaining_r = None if consumed_r is None else max(policy.daily_budget_r - consumed_r, _ZERO)

        ordered_closed = sorted(closed, key=lambda item: (item.exit_timestamp, item.trade_id))
        consecutive_losses = 0
        for item in reversed(ordered_closed):
            if item.net_realised_pnl < 0:
                consecutive_losses += 1
            else:
                break

        source_ids = sorted(
            {item.source_record_id for item in closed}
            | {source for item in open_items for source in item.source_record_ids}
            | {item.event_id for item in flows}
        )
        configuration_hash = _canonical_hash(asdict(policy))
        identity_payload = {
            "schema_version": self.schema_version,
            "trading_date": trading_date.isoformat(),
            "configuration_hash": configuration_hash,
            "source_record_ids": source_ids,
            "realised_net": realised_net,
            "open_cash": open_cash,
            "open_r": open_r,
            "floating": floating,
            "reasons": reasons,
        }
        report_id = _canonical_hash(identity_payload)[:32]

        return DailyRiskSnapshot(
            report_id=report_id,
            schema_version=self.schema_version,
            policy_version=policy.policy_version,
            trading_date=trading_date.isoformat(),
            currency=policy.currency,
            daily_budget_cash=policy.daily_budget_cash,
            daily_budget_r=policy.daily_budget_r,
            realised_net_pnl_cash=realised_net,
            realised_profit_cash=realised_profit,
            realised_loss_cash=realised_loss,
            realised_loss_r=realised_loss_r,
            open_risk_cash=open_cash,
            open_risk_r=open_r,
            open_floating_pnl_cash=floating,
            consumed_risk_cash=consumed_cash,
            consumed_risk_r=consumed_r,
            remaining_risk_cash=remaining_cash,
            remaining_risk_r=remaining_r,
            open_portfolio_heat_r=open_r,
            trade_count=len(closed),
            open_position_count=len(open_items),
            consecutive_losses=consecutive_losses,
            excluded_cash_flow_cash=excluded_cash_flow,
            evidence_complete=not reasons,
            evidence_reasons=tuple(reasons),
            source_record_ids=tuple(source_ids),
            configuration_hash=configuration_hash,
            generated_at_utc=generated,
        )

    @staticmethod
    def _unique_closed(items: Iterable[ClosedRiskTrade]) -> list[ClosedRiskTrade]:
        unique: dict[str, ClosedRiskTrade] = {}
        for item in items:
            existing = unique.get(item.trade_id)
            if existing is not None and existing != item:
                raise ValueError(f"conflicting closed trade: {item.trade_id}")
            unique[item.trade_id] = item
        return list(unique.values())

    @staticmethod
    def _unique_open(items: Iterable[OpenRiskPosition]) -> list[OpenRiskPosition]:
        unique: dict[str, OpenRiskPosition] = {}
        for item in items:
            existing = unique.get(item.position_id)
            if existing is not None and existing != item:
                raise ValueError(f"conflicting open position: {item.position_id}")
            unique[item.position_id] = item
        return list(unique.values())

    @staticmethod
    def _unique_flows(items: Iterable[CashFlowEvent]) -> list[CashFlowEvent]:
        unique: dict[str, CashFlowEvent] = {}
        for item in items:
            existing = unique.get(item.event_id)
            if existing is not None and existing != item:
                raise ValueError(f"conflicting cash-flow event: {item.event_id}")
            unique[item.event_id] = item
        return list(unique.values())


@dataclass(frozen=True, slots=True)
class DailyRiskLedgerPaths:
    data_dir: Path

    @property
    def forensic_reports(self) -> Path:
        return self.data_dir / "forensic_reports.jsonl"

    @property
    def deals(self) -> Path:
        return self.data_dir / "mt5_deals.jsonl"

    @property
    def orders(self) -> Path:
        return self.data_dir / "mt5_orders.jsonl"

    @property
    def position_snapshots(self) -> Path:
        return self.data_dir / "mt5_position_snapshots.jsonl"

    @property
    def history(self) -> Path:
        return self.data_dir / "portfolio" / "daily_risk_snapshots.jsonl"

    @property
    def latest(self) -> Path:
        return self.data_dir / "portfolio" / "latest_daily_risk.json"


class DailyRiskFileService:
    """Reconciles Edith file telemetry into an immutable daily risk snapshot."""

    def __init__(self, data_dir: str | Path = "data") -> None:
        self.paths = DailyRiskLedgerPaths(Path(data_dir))
        self.engine = DailyRiskLedgerEngine()

    def refresh(
        self,
        policy: DailyRiskPolicy,
        *,
        trading_date: date | None = None,
        generated_at: datetime | None = None,
    ) -> DailyRiskSnapshot:
        generated = generated_at or datetime.now(timezone.utc)
        if generated.tzinfo is None:
            raise ValueError("generated_at must be timezone-aware")
        day = trading_date or generated.astimezone(timezone.utc).date()

        forensic_rows = _read_jsonl(self.paths.forensic_reports)
        deal_rows = _read_jsonl(self.paths.deals)
        order_rows = _read_jsonl(self.paths.orders)
        snapshot_rows = _read_jsonl(self.paths.position_snapshots)

        closed = self._closed_trades(forensic_rows)
        open_positions, open_reasons = self._open_positions(deal_rows, order_rows, snapshot_rows)
        unreconciled = self._unreconciled_exit_positions(day, forensic_rows, deal_rows)
        reasons = list(open_reasons)
        if unreconciled:
            reasons.append(f"unreconciled_closed_positions:{','.join(unreconciled)}")

        snapshot = self.engine.build(
            trading_date=day,
            policy=policy,
            closed_trades=closed,
            open_positions=open_positions,
            generated_at=generated,
            additional_reasons=reasons,
        )
        self.persist(snapshot)
        return snapshot

    def persist(self, snapshot: DailyRiskSnapshot) -> None:
        payload = snapshot.to_dict()
        self.paths.history.parent.mkdir(parents=True, exist_ok=True)
        existing_ids = {
            str(row.get("report_id"))
            for row in _read_jsonl(self.paths.history)
            if row.get("report_id")
        }
        if snapshot.report_id not in existing_ids:
            with self.paths.history.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, default=_json_default, sort_keys=True, separators=(",", ":")) + "\n")
        _write_json(self.paths.latest, payload)

    @staticmethod
    def _closed_trades(rows: list[dict[str, Any]]) -> list[ClosedRiskTrade]:
        trades: list[ClosedRiskTrade] = []
        for row in rows:
            trade_id = str(row.get("trade_id") or row.get("position_id") or "")
            exit_value = row.get("exit_timestamp")
            if not trade_id or not exit_value:
                continue
            trades.append(
                ClosedRiskTrade(
                    trade_id=trade_id,
                    exit_timestamp=_timestamp(exit_value),
                    net_realised_pnl=_decimal(row.get("net_realised_pnl")),
                    realised_r=_decimal(row.get("r_multiple")),
                    source_record_id=f"forensic:{trade_id}",
                )
            )
        return trades

    @staticmethod
    def _open_positions(
        deals: list[dict[str, Any]],
        orders: list[dict[str, Any]],
        snapshots: list[dict[str, Any]],
    ) -> tuple[list[OpenRiskPosition], list[str]]:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for deal in deals:
            position_id = str(deal.get("position_id") or "")
            if position_id:
                grouped.setdefault(position_id, []).append(deal)

        latest_snapshots: dict[str, dict[str, Any]] = {}
        for row in snapshots:
            position_id = str(row.get("position_id") or "")
            if not position_id or not row.get("timestamp"):
                continue
            current = latest_snapshots.get(position_id)
            if current is None or _timestamp(row["timestamp"]) > _timestamp(current["timestamp"]):
                latest_snapshots[position_id] = row

        positions: list[OpenRiskPosition] = []
        reasons: list[str] = []
        for position_id, rows in sorted(grouped.items()):
            entries = [row for row in rows if int(row.get("entry", -1)) in _ENTRY_CODES]
            exits = [row for row in rows if int(row.get("entry", -1)) in _EXIT_CODES]
            if not entries or exits:
                continue
            entry = sorted(entries, key=lambda row: _timestamp(row["timestamp"]))[0]
            order = DailyRiskFileService._matching_order(entry, orders)
            latest = latest_snapshots.get(position_id)
            if latest is None:
                reasons.append(f"missing_open_position_snapshot:{position_id}")
            if order is None:
                reasons.append(f"missing_open_position_order:{position_id}")
            projected_cash = _optional_decimal(None if order is None else order.get("projected_risk_cash"))
            source_ids = [f"deal:{entry.get('ticket', entry.get('order', position_id))}"]
            if order is not None:
                source_ids.append(f"order:{order.get('order') or order.get('deal') or position_id}")
            if latest is not None:
                source_ids.append(f"position_snapshot:{position_id}:{latest.get('timestamp')}")
            positions.append(
                OpenRiskPosition(
                    position_id=position_id,
                    snapshot_timestamp=None if latest is None else _timestamp(latest["timestamp"]),
                    projected_risk_cash=projected_cash,
                    projected_risk_r=Decimal("1") if projected_cash is not None else None,
                    floating_pnl=_decimal(None if latest is None else latest.get("profit")),
                    source_record_ids=tuple(source_ids),
                )
            )
        return positions, reasons

    @staticmethod
    def _matching_order(entry: dict[str, Any], orders: list[dict[str, Any]]) -> dict[str, Any] | None:
        candidates = [
            row
            for row in orders
            if row.get("status") == "accepted"
            and (
                str(row.get("deal")) == str(entry.get("ticket"))
                or str(row.get("order")) == str(entry.get("order"))
            )
        ]
        return candidates[-1] if candidates else None

    @staticmethod
    def _unreconciled_exit_positions(
        trading_date: date,
        forensic: list[dict[str, Any]],
        deals: list[dict[str, Any]],
    ) -> list[str]:
        reconciled = {
            str(row.get("trade_id") or row.get("position_id"))
            for row in forensic
            if row.get("trade_id") or row.get("position_id")
        }
        exits = {
            str(row.get("position_id"))
            for row in deals
            if row.get("position_id")
            and int(row.get("entry", -1)) in _EXIT_CODES
            and row.get("timestamp")
            and _timestamp(row["timestamp"]).date() == trading_date
        }
        return sorted(exits - reconciled)
