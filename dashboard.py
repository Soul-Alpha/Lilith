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
            if isinstance(value, dict):
                rows.append(value)
    return pd.DataFrame(rows)


def age_seconds(status: dict[str, Any]) -> float | None:
    raw = status.get("heartbeat_at")
    if not raw:
        return None
    heartbeat = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
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
st.caption("Live MT5 demo-account execution telemetry, signals, broker orders, deals, and research intelligence.")

with st.sidebar:
    st.subheader("Runtime files")
    for path in (STATUS_PATH, SIGNALS_PATH, ORDERS_PATH, DEALS_PATH):
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
        st.warning(f"Notebook online, but MT5 broker connection is {status.get('broker_connection', 'unknown')}.")
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

    g, h, i, j, k = st.columns(5)
    g.metric("Iteration", f"{int(status.get('iteration', 0)):,}")
    h.metric("Signals", f"{int(status.get('signals_seen', len(signals))):,}")
    i.metric("Orders accepted", f"{int(status.get('orders_sent', 0)):,}")
    j.metric("Broker deals", f"{len(deals):,}")
    k.metric("Last signal", str(status.get("last_signal", "—")))

    st.caption(
        f"Mode: {status.get('mode', 'unknown')} · Server: {status.get('account_server', '—')} · "
        f"Symbol: {status.get('symbol', '—')} · Timeframe: {status.get('timeframe', '—')} · "
        f"Last order: {status.get('last_order_status', '—')}"
    )

    signal_tab, order_tab, deal_tab = st.tabs(["Signals", "MT5 orders", "MT5 deals"])
    with signal_tab:
        if signals.empty:
            st.info("Awaiting MT5 market signal telemetry.")
        else:
            cols = [c for c in ["timestamp", "iteration", "symbol", "timeframe", "signal", "decision", "score", "fast_sma", "slow_sma", "atr", "reason"] if c in signals]
            st.dataframe(signals.tail(25).iloc[::-1][cols], use_container_width=True, hide_index=True)
    with order_tab:
        if orders.empty:
            st.info("No MT5 order attempts recorded yet.")
        else:
            cols = [c for c in ["timestamp", "status", "order", "deal", "symbol", "side", "volume", "price", "sl", "tp", "retcode", "comment"] if c in orders]
            st.dataframe(orders.tail(25).iloc[::-1][cols], use_container_width=True, hide_index=True)
    with deal_tab:
        if deals.empty:
            st.info("No Edith MT5 deals recorded in this runtime session.")
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

forensic_tab, sculptor_tab = st.tabs(["Trade Forensics", "Feature Sculptor"])
with forensic_tab:
    if forensic.empty:
        st.info("Awaiting completed forensic records. MT5 runtime deals remain operational telemetry until reconciled into forensic reports.")
    else:
        cols = [c for c in ["trade_id", "exit_timestamp", "exit_reason", "net_realised_pnl", "r_multiple", "mfe_r", "mae_r", "management_quality", "primary_cause"] if c in forensic]
        st.dataframe(forensic[cols], use_container_width=True, hide_index=True)
with sculptor_tab:
    if sculptor.empty:
        st.info("Awaiting feature-sculptor results.")
    else:
        cols = [c for c in ["fingerprint", "sample_size", "win_rate", "expectancy_r", "profit_factor", "max_drawdown", "stability_score", "approved", "rejection_reasons"] if c in sculptor]
        st.dataframe(sculptor[cols], use_container_width=True, hide_index=True)
