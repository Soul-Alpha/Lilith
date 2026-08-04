from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from inspect import signature
import os
from typing import Any

from .intelligence.daily_risk import DailyRiskFileService, DailyRiskPolicy
from .mt5_demo import MT5DemoRuntime, append_jsonl, now
from .mt5_reconciliation import MT5ForensicReconciler
from .mt5_terminal import initialize_terminal, terminal_identity


class OwnershipAwareRuntimeLock:
    """Prevent a runtime from releasing a lock it never acquired.

    The underlying lock remains fail-closed. This wrapper records ownership,
    adds owner diagnostics, and never removes or overrides an uncertain lock.
    """

    def __init__(self, delegate: Any) -> None:
        self._delegate = delegate
        self.acquired = False

    @property
    def path(self) -> Any:
        return self._delegate.path

    def _owner_details(self) -> str:
        try:
            value = self.path.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeDecodeError):
            return "owner metadata unavailable"
        return value or "owner metadata empty"

    def acquire(self) -> None:
        try:
            self._delegate.acquire()
        except RuntimeError as exc:
            owner = self._owner_details()
            raise RuntimeError(
                f"{exc}. Lock owner: {owner}. Stop the previous Edith notebook "
                "kernel/process before starting another runtime. Only delete the "
                "lock after confirming that its PID is no longer active."
            ) from exc
        self.acquired = True

    def release(self) -> None:
        if not self.acquired:
            return
        try:
            self._delegate.release()
        finally:
            self.acquired = False


class ReconciledMT5DemoRuntime(MT5DemoRuntime):
    """Adds analytics-only lifecycle capture, reconciliation, and terminal binding."""

    def __init__(self, mt5: Any | None = None, data_dir: str = "data") -> None:
        parameters = signature(MT5DemoRuntime.__init__).parameters
        kwargs: dict[str, Any] = {}
        if "data_dir" in parameters:
            kwargs["data_dir"] = data_dir
        if "mt5" in parameters:
            kwargs["mt5"] = mt5
        super().__init__(**kwargs)
        if "mt5" not in parameters and mt5 is not None:
            self.mt5 = mt5

        # MT5DemoRuntime.run() always calls release() in its finalizer. Track
        # ownership so a process rejected during acquire() cannot delete a lock
        # owned by another active runtime. This also makes repeated release safe.
        self.lock = OwnershipAwareRuntimeLock(self.lock)
        self.position_snapshots_path = self.data_dir / "mt5_position_snapshots.jsonl"
        self.reconciler = MT5ForensicReconciler(self.data_dir)
        self.daily_risk_service = DailyRiskFileService(self.data_dir)
        self.terminal_path = None

    def connect(self) -> None:
        mt5 = self._import_mt5()
        self.lock.acquire()
        try:
            self.terminal_path = initialize_terminal(mt5)
            if not mt5.login(self.login, password=self.password, server=self.server):
                raise RuntimeError(f"MT5 login failed: {mt5.last_error()}")
            account, terminal = self.validate_identity()
            if not mt5.symbol_select(self.symbol, True):
                raise RuntimeError(f"Unable to select {self.symbol}: {mt5.last_error()}")
            self.initial_equity = float(account.equity)
            self.publish(
                connection="Online",
                broker_connection="Connected",
                runtime="running",
                mode="mt5-demo",
                session_id=self.session_id,
                started_at=now(),
                symbol=self.symbol,
                timeframe=self.timeframe,
                account_login=int(account.login),
                account_server=str(account.server),
                account_trade_mode="demo",
                account_balance=float(account.balance),
                account_equity=float(account.equity),
                account_profit=float(account.profit),
                currency=str(account.currency),
                iteration=0,
                signals_seen=0,
                orders_sent=0,
                open_positions=0,
                pending_orders=0,
                last_signal="HOLD",
                message="Connected to governed MT5 demo account.",
                **terminal_identity(terminal, self.terminal_path),
            )
        except Exception:
            try:
                mt5.shutdown()
            finally:
                self.lock.release()
            raise

    def _record_position_snapshots(self) -> int:
        mt5 = self._import_mt5()
        tick = mt5.symbol_info_tick(self.symbol)
        if tick is None:
            return 0
        owned, _ = self.owned_exposure()
        for position in owned:
            append_jsonl(self.position_snapshots_path, {
                "timestamp": now(), "session_id": self.session_id,
                "position_id": int(getattr(position, "ticket", 0)),
                "symbol": self.symbol, "side": "BUY" if int(getattr(position, "type", 0)) == int(mt5.POSITION_TYPE_BUY) else "SELL",
                "volume": float(getattr(position, "volume", 0.0)),
                "price_open": float(getattr(position, "price_open", 0.0)),
                "bid": float(tick.bid), "ask": float(tick.ask),
                "sl": float(getattr(position, "sl", 0.0)), "tp": float(getattr(position, "tp", 0.0)),
                "profit": float(getattr(position, "profit", 0.0)),
                "magic": int(getattr(position, "magic", 0)), "mode": "mt5-demo",
            })
        return len(owned)

    def _refresh_daily_risk(self, status: dict[str, Any]) -> dict[str, Any]:
        try:
            policy = DailyRiskPolicy(
                daily_budget_cash=Decimal(os.getenv("EDITH_PORTFOLIO_DAILY_BUDGET_CASH", str(self.max_daily_loss))),
                daily_budget_r=Decimal(os.getenv("EDITH_PORTFOLIO_DAILY_BUDGET_R", "2.0")),
                currency=str(status.get("currency") or os.getenv("EDITH_PORTFOLIO_CURRENCY", "USD")),
            )
            snapshot = self.daily_risk_service.refresh(policy)
        except Exception as exc:
            status.update({
                "daily_risk_ledger_status": "error",
                "daily_risk_ledger_error": repr(exc),
                "daily_risk_advisory_only": True,
            })
            return status

        status.update({
            "daily_risk_ledger_status": "complete" if snapshot.evidence_complete else "awaiting_evidence",
            "daily_risk_report_id": snapshot.report_id,
            "daily_risk_consumed_cash": None if snapshot.consumed_risk_cash is None else float(snapshot.consumed_risk_cash),
            "daily_risk_remaining_cash": None if snapshot.remaining_risk_cash is None else float(snapshot.remaining_risk_cash),
            "daily_risk_consumed_r": None if snapshot.consumed_risk_r is None else float(snapshot.consumed_risk_r),
            "daily_risk_remaining_r": None if snapshot.remaining_risk_r is None else float(snapshot.remaining_risk_r),
            "daily_risk_open_heat_r": None if snapshot.open_portfolio_heat_r is None else float(snapshot.open_portfolio_heat_r),
            "daily_risk_advisory_only": True,
        })
        return status

    def step(self) -> dict[str, Any]:
        self.validate_identity()
        new_deals_before = self.record_deals()
        snapshots = self._record_position_snapshots()
        status = super().step()
        new_deals_after = self.record_deals()
        forensic_added = self.reconciler.reconcile()
        status["new_deals"] = int(status.get("new_deals", 0)) + new_deals_before + new_deals_after
        status["position_snapshots"] = snapshots
        status["forensic_reports_added"] = forensic_added
        status["reconciliation_at"] = datetime.now(timezone.utc).isoformat()
        status = self._refresh_daily_risk(status)
        if new_deals_before or new_deals_after or snapshots or forensic_added:
            status["message"] = "Governed MT5 telemetry, forensic reconciliation, and daily risk evidence received."
        return self.publish(**status)


def run_from_environment() -> None:
    ReconciledMT5DemoRuntime().run()
