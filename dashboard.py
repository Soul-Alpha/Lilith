from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

st.set_page_config(page_title="Edith Command Centre", page_icon="🧠", layout="wide")

DATA_PATH = Path(os.environ.get("EDITH_FORENSICS_PATH", "data/forensic_reports.jsonl"))
SCULPTOR_PATH = Path(os.environ.get("EDITH_SCULPTOR_PATH", "data/feature_sculptor_results.jsonl"))
STATUS_PATH = Path(os.environ.get("EDITH_RUNTIME_STATUS_PATH", "data/runtime_status.json"))
SIGNALS_PATH = Path(os.environ.get("EDITH_SIGNALS_PATH", "data/signals.jsonl"))
DEMO_TRADES_PATH = Path(os.environ.get("EDITH_DEMO_TRADES_PATH", "data/demo_trades.jsonl"))
HEARTBEAT_STALE_SECONDS = int(os.environ.get("EDITH_HEARTBEAT_STALE_SECONDS", "20"))


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
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON on line {line_number}: {exc}") from exc
            if not isinstance(value, dict):
                raise ValueError(f"Line {line_number} must contain a JSON object")
            rows.append(value)
    return pd.DataFrame(rows)


def money(value: float) -> str:
    return f"${value:,.2f}"


def heartbeat_age_seconds(status: dict[str, Any]) -> float | None:
    raw = status.get("heartbeat_at")
    if not raw:
        return None
    try:
        heartbeat = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    if heartbeat.tzinfo is None:
        heartbeat = heartbeat.replace(tzinfo=timezone.utc)
    return max(0.0, (datetime.now(timezone.utc) - heartbeat.astimezone(timezone.utc)).total_seconds())


st.title("Edith Command Centre")
st.caption("Demo-simulation runtime telemetry plus read-only forensic and research intelligence.")

with st.sidebar:
    st.subheader("Data sources")
    st.code(str(STATUS_PATH))
    st.code(str(SIGNALS_PATH))
    st.code(str(DEMO_TRADES_PATH))
    st.code(str(DATA_PATH))
    st.code(str(SCULPTOR_PATH))
    st.write("Execution mode:", os.environ.get("LILITH_EXECUTION_MODE", "simulation"))
    refresh = st.button("Refresh all data", use_container_width=True)

if refresh:
    st.cache_data.clear()
    st.rerun()


@st.fragment(run_every=5)
def live_runtime_panel() -> None:
    try:
        status = load_json(STATUS_PATH)
        signals = load_jsonl(SIGNALS_PATH)
        demo_trades = load_jsonl(DEMO_TRADES_PATH)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        st.error(f"Unable to load runtime telemetry: {exc}")
        return

    age = heartbeat_age_seconds(status)
    connected = bool(status) and status.get("runtime") == "running" and age is not None and age <= HEARTBEAT_STALE_SECONDS
    connection = "Online" if connected else "Offline"
    detail = status.get("message", "No telemetry received.") if status else "No telemetry received."

    st.subheader("Live demo runtime")
    if connected:
        st.success(f"Notebook connected — heartbeat {age:.1f}s ago")
    else:
        stale = f" Last heartbeat was {age:.1f}s ago." if age is not None else ""
        st.warning(f"Notebook offline — {detail}{stale}")

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Connection", connection)
    c2.metric("Runtime", str(status.get("runtime", "unknown")))
    c3.metric("Iteration", f"{int(status.get('iteration', 0)):,}")
    c4.metric("Signals", f"{int(status.get('signals_seen', len(signals))):,}")
    c5.metric("Demo trades", f"{int(status.get('demo_trades', len(demo_trades))):,}")
    c6.metric("Last signal", str(status.get("last_signal", "—")))

    st.caption(
        f"Mode: {status.get('mode', 'unknown')} · "
        f"Symbol: {status.get('symbol', '—')} · "
        f"Timeframe: {status.get('timeframe', '—')} · "
        f"Session: {status.get('session_id', '—')}"
    )

    left, right = st.columns(2)
    with left:
        st.markdown("#### Recent signals")
        if signals.empty:
            st.info("Awaiting notebook signal telemetry.")
        else:
            columns = [c for c in ["timestamp", "iteration", "symbol", "timeframe", "signal", "decision", "score", "reason"] if c in signals.columns]
            st.dataframe(signals.tail(15).iloc[::-1][columns], use_container_width=True, hide_index=True)
    with right:
        st.markdown("#### Recent demo trades")
        if demo_trades.empty:
            st.info("No demo trades generated yet.")
        else:
            columns = [c for c in ["timestamp", "trade_id", "symbol", "side", "status", "net_realised_pnl", "r_multiple"] if c in demo_trades.columns]
            st.dataframe(demo_trades.tail(15).iloc[::-1][columns], use_container_width=True, hide_index=True)


live_runtime_panel()
st.divider()

try:
    reports = load_jsonl(DATA_PATH)
    sculptor_results = load_jsonl(SCULPTOR_PATH)
except (OSError, ValueError) as exc:
    st.error(f"Unable to load Edith records: {exc}")
    st.stop()

for column in ("net_realised_pnl", "r_multiple", "mfe_r", "mae_r", "peak_floating_pnl", "trough_floating_pnl"):
    if column in reports:
        reports[column] = pd.to_numeric(reports[column], errors="coerce")

for column in ("expectancy_pnl", "expectancy_r", "profit_factor", "max_drawdown", "stability_score", "sample_size"):
    if column in sculptor_results:
        sculptor_results[column] = pd.to_numeric(sculptor_results[column], errors="coerce")

forensics_tab, sculptor_tab = st.tabs(["Trade Forensics", "Feature Sculptor"])

with forensics_tab:
    if reports.empty:
        st.info(
            "Awaiting forensic records. Configure EDITH_FORENSICS_PATH or write JSON Lines records to "
            "data/forensic_reports.jsonl. Demo trades are displayed separately and are not treated as forensic evidence."
        )
    else:
        net_pnl = float(reports.get("net_realised_pnl", pd.Series(dtype=float)).fillna(0).sum())
        trade_count = len(reports)
        wins = int((reports.get("net_realised_pnl", pd.Series(dtype=float)).fillna(0) > 0).sum())
        win_rate = wins / trade_count * 100 if trade_count else 0.0
        avg_r_series = reports.get("r_multiple", pd.Series(dtype=float)).dropna()
        avg_r = float(avg_r_series.mean()) if not avg_r_series.empty else 0.0
        profit_surrendered = int(
            reports.get("management_quality", pd.Series(dtype=str))
            .isin(["profit_surrendered", "breakeven_or_trailing_candidate"])
            .sum()
        )

        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Net realised PnL", money(net_pnl))
        c2.metric("Closed trades", f"{trade_count:,}")
        c3.metric("Win rate", f"{win_rate:.1f}%")
        c4.metric("Average R", f"{avg_r:.2f}R")
        c5.metric("Profit surrendered", f"{profit_surrendered:,}")

        st.divider()
        left, right = st.columns([2, 1])
        with left:
            st.subheader("Cumulative realised performance ($)")
            performance = reports.copy()
            if "exit_timestamp" in performance:
                performance["exit_timestamp"] = pd.to_datetime(performance["exit_timestamp"], errors="coerce", utc=True)
                performance = performance.sort_values("exit_timestamp")
            performance["cumulative_pnl"] = performance.get("net_realised_pnl", 0).fillna(0).cumsum()
            st.line_chart(performance, y="cumulative_pnl")
        with right:
            st.subheader("Exit distribution")
            if "exit_reason" in reports:
                st.bar_chart(reports["exit_reason"].value_counts())
            else:
                st.info("Exit reason data unavailable")

        st.subheader("Loss-forensics breakdown")
        forensic_columns = [
            "trade_id", "exit_reason", "net_realised_pnl", "r_multiple", "mfe_r", "mae_r",
            "direction_quality", "entry_quality", "stop_quality", "target_quality",
            "management_quality", "primary_cause",
        ]
        visible = [column for column in forensic_columns if column in reports.columns]
        st.dataframe(reports[visible], use_container_width=True, hide_index=True)

        st.subheader("Primary causes")
        if "primary_cause" in reports:
            st.bar_chart(reports["primary_cause"].value_counts())

with sculptor_tab:
    st.caption("Research-only rankings. Approved means evidence gates passed; it does not authorize live strategy changes.")
    if sculptor_results.empty:
        st.info("Awaiting feature-sculptor results at data/feature_sculptor_results.jsonl.")
    else:
        approved = sculptor_results.get("approved", pd.Series(dtype=bool)).fillna(False).astype(bool)
        a1, a2, a3 = st.columns(3)
        a1.metric("Fingerprints analysed", f"{len(sculptor_results):,}")
        a2.metric("Evidence-approved", f"{int(approved.sum()):,}")
        best_expectancy = float(sculptor_results.get("expectancy_r", pd.Series(dtype=float)).max())
        a3.metric("Best expectancy", f"{best_expectancy:.2f}R")

        leaderboard_columns = [
            "fingerprint", "sample_size", "win_rate", "expectancy_pnl", "expectancy_r",
            "profit_factor", "max_drawdown", "stability_score", "approved", "rejection_reasons",
        ]
        visible = [column for column in leaderboard_columns if column in sculptor_results.columns]
        st.dataframe(sculptor_results[visible], use_container_width=True, hide_index=True)

with st.expander("Record contracts"):
    st.write(
        "Runtime heartbeat, demo signals, and demo trades are operational telemetry only. "
        "Forensic and sculptor inputs remain separate JSON Lines evidence streams."
    )
