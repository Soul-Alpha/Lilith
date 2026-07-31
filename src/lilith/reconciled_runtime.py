from __future__ import annotations

from datetime import datetime, timezone
from inspect import signature
from typing import Any

from .mt5_demo import MT5DemoRuntime, append_jsonl, now
from .mt5_reconciliation import MT5ForensicReconciler


class ReconciledMT5DemoRuntime(MT5DemoRuntime):
    """Adds analytics-only lifecycle capture and reconciliation to Edith execution."""

    def __init__(self, mt5: Any | None = None, data_dir: str = "data") -> None:
        # Support both the current injectable MT5 runtime constructor and older
        # local editable installs whose base constructor only accepts data_dir.
        parameters = signature(MT5DemoRuntime.__init__).parameters
        kwargs: dict[str, Any] = {}
        if "data_dir" in parameters:
            kwargs["data_dir"] = data_dir
        if "mt5" in parameters:
            kwargs["mt5"] = mt5
        super().__init__(**kwargs)
        if "mt5" not in parameters and mt5 is not None:
            self.mt5 = mt5

        self.position_snapshots_path = self.data_dir / "mt5_position_snapshots.jsonl"
        self.reconciler = MT5ForensicReconciler(self.data_dir)

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

    def step(self) -> dict[str, Any]:
        # Capture broker changes every poll, not only when a new candle closes.
        self.validate_identity()
        new_deals_before = self.record_deals()
        snapshots = self._record_position_snapshots()
        status = super().step()
        new_deals_after = self.record_deals()
        forensic_added = self.reconciler.reconcile()
        if new_deals_before or new_deals_after or snapshots or forensic_added:
            # Calculate aggregated metrics and update status before publishing
            status["new_deals"] = int(status.get("new_deals", 0)) + new_deals_before + new_deals_after
            status["position_snapshots"] = snapshots
            status["forensic_reports_added"] = forensic_added
            status["reconciliation_at"] = datetime.now(timezone.utc).isoformat()
            status["message"] = "Governed MT5 telemetry and forensic reconciliation received."
            status = self.publish(**status)
        return status


def run_from_environment() -> None:
    ReconciledMT5DemoRuntime().run()
