from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

st.set_page_config(page_title="Edith Command Centre", page_icon="🧠", layout="wide")

STATUS_PATH = Path(os.getenv("EDITH_RUNTIME_STATUS_PATH", "data/runtime_status.json"))
SIGNALS_PATH = Path(os.getenv("EDITH_SIGNALS_PATH", "data/signals.jsonl"))
ORDERS_PATH = Path(os.getenv("EDITH_MT5_ORDERS_PATH", "data/mt5_orders.jsonl"))
DEALS_PATH = Path(os.getenv("EDITH_MT5_DEALS_PATH", "data/mt5_deals.jsonl"))
FORENSICS_PATH = Path(os.getenv("EDITH_FORENSICS_PATH", "data/forensic_reports.jsonl"))
SCULPTOR_PATH = Path(os.getenv("EDITH_SCULPTOR_PATH", "data/feature_sculptor_results.jsonl"))
STALE_SECONDS = int(os.getenv("EDITH_HEARTBEAT_STALE_SECONDS", "45"))


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def load_jsonl(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON in {path} line {number}: {exc}") from exc
            if not isinstance(value, dict):
                raise ValueError(f"{path} line {number} must contain a JSON object")
            rows.append(value)
    return pd.DataFrame(rows)


def age_seconds(status: dict[str, Any]) -> float | None:
    raw = status.get("heartbeat_at")
    if not raw:
        return None
    try:
        heartbeat = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if heartbeat.tzinfo is None:
        heartbeat = heartbeat.replace(tzinfo=timezone.utc)
    return max(0.0, (datetime.now(timezone.utc) - heartbeat.astimezone(timezone.utc)).total_seconds())


def money(value: Any, currency: str = "USD") -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = 0.0
    return f"{currency} {number:,.2f}"


st.title("Edith Command Centre")
st.caption("Governed MT5 demo execution telemetry with preserved forensic and feature-research intelligence.")

with st.sidebar:
    st.subheader("Runtime files")
    for path in (STATUS_PATH, SIGNALS_PATH, ORDERS_PATH, DEALS_PATH, FORENSICS_PATH, SCULPTOR_PATH):
        st.code(str(path))
    st.write("Requested mode:", os.getenv("LILITH_EXECUTION_MODE", "not set"))
    if st.button("Refresh all data", use_container_width=True):
        st.rerun()


@st.fragment(run_every=5)
def runtime_panel() -> None:
    try:
        status = load_json(STATUS_PATH)
        signals = load_jsonl(SIGNALS_PATH)
        orders = load_jsonl(ORDERS_PATH)
        deals = load_jsonl(DEALS_PATH)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        st.error(f"Unable to load MT5 telemetry: {exc}")
        return

    age = age_seconds(status)
    notebook_online = bool(status) and status.get("runtime") == "running" and age is not None and age <= STALE_SECONDS
    broker_online = notebook_online and status.get("broker_connection") == "Connected" and status.get("account_trade_mode") == "demo"
    currency = str(status.get("currency", "USD"))

    if broker_online:
        st.success(f"MT5 demo connected — account {status.get('account_login', '—')} · heartbeat {age:.1f}s ago")
    elif notebook_online:
        st.warning(f"Notebook online, but MT5 connection is {status.get('broker_connection', 'unknown')}.")
    else:
        stale = f" Last heartbeat {age:.1f}s ago." if age is not None else ""
        st.error(f"Edith offline — {status.get('message', 'No runtime telemetry.')}{stale}")

    a, b, c, d, e, f = st.columns(6)
    a.metric("Notebook", "Online" if notebook_online else "Offline")
    b.metric("MT5 demo", "Connected" if broker_online else "Disconnected")
    c.metric("Balance", money(status.get("account_balance"), currency))
    d.metric("Equity", money(status.get("account_equity"), currency))
    e.metric("Floating PnL", money(status.get("account_profit"), currency))
    f.metric("Open positions", f"{int(status.get('open_positions', 0)):,}")

    g, h, i, j, k, l = st.columns(6)
    g.metric("Pending orders", f"{int(status.get('pending_orders', 0)):,}")
    h.metric("Iteration", f"{int(status.get('iteration', 0)):,}")
    i.metric("Signals", f"{int(status.get('signals_seen', len(signals))):,}")
    j.metric("Orders accepted", f"{int(status.get('orders_sent', 0)):,}")
    k.metric("Daily realised", money(status.get("daily_realised_pnl"), currency))
    l.metric("Last signal", str(status.get("last_signal", "—")))

    st.caption(
        f"Mode: {status.get('mode', 'unknown')} · Server: {status.get('account_server', '—')} · "
        f"Symbol: {status.get('symbol', '—')} · Timeframe: {status.get('timeframe', '—')} · "
        f"Last order: {status.get('last_order_status', '—')}"
    )

    gate_mode = str(status.get("last_spread_gate_mode", "?"))
    gate_label = {"normal": "Normal", "high_grade_override": "High-grade override",
                  "rejected": "Rejected"}.get(gate_mode, gate_mode)
    spread_atr = status.get("last_spread_atr_fraction")
    spread_atr_label = "?" if spread_atr is None else f"{float(spread_atr) * 100:.2f}%"
    m, n, o, p, q, r = st.columns(6)
    m.metric("Signal score", "?" if status.get("last_score") is None else f"{float(status.get('last_score')):.2f}")
    n.metric("Measured spread", "?" if status.get("last_spread_points") is None else f"{float(status.get('last_spread_points')):.1f} pts")
    o.metric("Normal spread limit", "?" if status.get("last_normal_spread_limit_points") is None else f"{float(status.get('last_normal_spread_limit_points')):.1f} pts")
    p.metric("Effective spread limit", "?" if status.get("last_effective_spread_limit_points") is None else f"{float(status.get('last_effective_spread_limit_points')):.1f} pts")
    q.metric("Spread as ATR", spread_atr_label)
    r.metric("Spread gate", gate_label)
    s, t, u = st.columns(3)
    s.metric("High-grade override used", "Yes" if status.get("last_high_grade_override") else "No")
    t.metric("Override state", "Consumed" if status.get("high_grade_override_consumed") else "Armed")
    u.metric("Regime", str(status.get("high_grade_regime_direction", "?")))
    if status.get("last_high_grade_override"):
        st.warning(
            "High-grade spread override used. Signal score met the governed threshold and spread remained within both the hard and ATR-relative limits."
        )
    if status.get("last_rejection_reason"):
        st.caption(
            f"Last rejection: {status.get('last_rejection_category', 'unknown')} ? {status.get('last_rejection_reason')}"
        )

    signal_tab, order_tab, deal_tab = st.tabs(["Signals", "MT5 orders", "MT5 deals"])
    with signal_tab:
        if signals.empty:
            st.info("Awaiting completed-candle MT5 signal telemetry.")
        else:
            cols = [c for c in ["timestamp", "candle_time", "signal_key", "symbol", "timeframe", "signal", "decision", "score", "fast_sma", "slow_sma", "atr", "reason"] if c in signals]
            st.dataframe(signals.tail(25).iloc[::-1][cols], use_container_width=True, hide_index=True)
    with order_tab:
        if orders.empty:
            st.info("No MT5 order attempts recorded yet.")
        else:
            cols = [c for c in ["timestamp", "status", "rejection_category", "rejection_reason", "spread_gate_mode", "high_grade_override", "signal_score", "spread_points", "normal_spread_limit_points", "effective_spread_limit_points", "spread_atr_fraction", "order", "deal", "symbol", "side", "volume", "price", "sl", "tp", "projected_risk_cash", "retcode", "comment"] if c in orders]
            st.dataframe(orders.tail(25).iloc[::-1][cols], use_container_width=True, hide_index=True)
    with deal_tab:
        if deals.empty:
            st.info("No Edith MT5 deals recorded yet.")
        else:
            cols = [c for c in ["timestamp", "ticket", "order", "position_id", "symbol", "entry", "volume", "price", "profit", "commission", "swap", "fee", "comment"] if c in deals]
            st.dataframe(deals.tail(25).iloc[::-1][cols], use_container_width=True, hide_index=True)


runtime_panel()
st.divider()

try:
    forensic = load_jsonl(FORENSICS_PATH)
    sculptor = load_jsonl(SCULPTOR_PATH)
except (OSError, ValueError) as exc:
    st.error(f"Unable to load research records: {exc}")
    st.stop()

for column in ("net_realised_pnl", "r_multiple", "mfe_r", "mae_r", "peak_floating_pnl", "trough_floating_pnl"):
    if column in forensic:
        forensic[column] = pd.to_numeric(forensic[column], errors="coerce")
for column in ("expectancy_pnl", "expectancy_r", "profit_factor", "max_drawdown", "stability_score", "sample_size", "win_rate"):
    if column in sculptor:
        sculptor[column] = pd.to_numeric(sculptor[column], errors="coerce")

forensic_tab, sculptor_tab = st.tabs(["Trade Forensics", "Feature Sculptor"])
with forensic_tab:
    if forensic.empty:
        st.info("Awaiting completed forensic reports. MT5 runtime deals remain operational telemetry until reconciled.")
    else:
        net_pnl = float(forensic.get("net_realised_pnl", pd.Series(dtype=float)).fillna(0).sum())
        trade_count = len(forensic)
        wins = int((forensic.get("net_realised_pnl", pd.Series(dtype=float)).fillna(0) > 0).sum())
        win_rate = wins / trade_count * 100 if trade_count else 0.0
        avg_r_series = forensic.get("r_multiple", pd.Series(dtype=float)).dropna()
        avg_r = float(avg_r_series.mean()) if not avg_r_series.empty else 0.0
        surrendered = int(forensic.get("management_quality", pd.Series(dtype=str)).isin(["profit_surrendered", "breakeven_or_trailing_candidate"]).sum())

        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Net realised PnL", money(net_pnl))
        c2.metric("Closed trades", f"{trade_count:,}")
        c3.metric("Win rate", f"{win_rate:.1f}%")
        c4.metric("Average R", f"{avg_r:.2f}R")
        c5.metric("Profit surrendered", f"{surrendered:,}")

        left, right = st.columns([2, 1])
        with left:
            performance = forensic.copy()
            if "exit_timestamp" in performance:
                performance["exit_timestamp"] = pd.to_datetime(performance["exit_timestamp"], errors="coerce", utc=True)
                performance = performance.sort_values("exit_timestamp")
            performance["cumulative_pnl"] = performance.get("net_realised_pnl", 0).fillna(0).cumsum()
            st.subheader("Cumulative realised performance")
            st.line_chart(performance, y="cumulative_pnl")
        with right:
            st.subheader("Exit distribution")
            if "exit_reason" in forensic:
                st.bar_chart(forensic["exit_reason"].value_counts())
            else:
                st.info("Exit reason data unavailable")

        cols = [c for c in ["trade_id", "exit_timestamp", "exit_reason", "net_realised_pnl", "r_multiple", "mfe_r", "mae_r", "direction_quality", "entry_quality", "stop_quality", "target_quality", "management_quality", "primary_cause"] if c in forensic]
        st.subheader("Loss-forensics breakdown")
        st.dataframe(forensic[cols], use_container_width=True, hide_index=True)
        if "primary_cause" in forensic:
            st.subheader("Primary causes")
            st.bar_chart(forensic["primary_cause"].value_counts())

with sculptor_tab:
    st.caption("Research-only rankings. Approval does not authorize automatic strategy mutation.")
    if sculptor.empty:
        st.info("Awaiting feature-sculptor results.")
    else:
        approved = sculptor.get("approved", pd.Series(dtype=bool)).fillna(False).astype(bool)
        a1, a2, a3 = st.columns(3)
        a1.metric("Fingerprints analysed", f"{len(sculptor):,}")
        a2.metric("Evidence-approved", f"{int(approved.sum()):,}")
        expectancy = sculptor.get("expectancy_r", pd.Series(dtype=float)).dropna()
        a3.metric("Best expectancy", f"{float(expectancy.max()) if not expectancy.empty else 0.0:.2f}R")
        cols = [c for c in ["fingerprint", "sample_size", "win_rate", "expectancy_pnl", "expectancy_r", "profit_factor", "max_drawdown", "stability_score", "approved", "rejection_reasons"] if c in sculptor]
        st.dataframe(sculptor[cols], use_container_width=True, hide_index=True)
