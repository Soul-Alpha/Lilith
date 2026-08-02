from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd
import streamlit as st

REPORT_PATH = Path(os.getenv("JAXTER_AMD_REPORT_PATH", "data/jaxter/amd_structure_report.json"))
TRADES_PATH = Path(os.getenv("JAXTER_AMD_TRADES_PATH", "data/jaxter/amd_structure_trades.jsonl"))


def _load_report() -> dict:
    if not REPORT_PATH.exists():
        return {}
    value = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {}


def _load_trades() -> pd.DataFrame:
    if not TRADES_PATH.exists():
        return pd.DataFrame()
    rows = [json.loads(line) for line in TRADES_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]
    return pd.json_normalize(rows)


def render_jaxter_dashboard() -> None:
    st.divider()
    st.header("Jaxter · Strategy Assistant")
    st.caption("Isolated research engine. Jaxter cannot place orders, alter Edith, or authorize execution.")
    try:
        report, trades = _load_report(), _load_trades()
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        st.error(f"Unable to load Jaxter evidence: {exc}")
        return
    if not report:
        st.info("Awaiting a 3–6 month AMD-Structure historical research run.")
        return
    summary = report.get("summary", {})
    st.warning("Research only — execution authorization is disabled pending validated historical evidence.")
    a, b, c, d, e = st.columns(5)
    a.metric("Signals", int(summary.get("signals", 0)))
    b.metric("Resolved", int(summary.get("resolved", 0)))
    c.metric("Win rate", f"{float(summary.get('win_rate', 0)) * 100:.1f}%")
    d.metric("Expectancy", f"{float(summary.get('expectancy_r', 0)):.2f}R")
    e.metric("Net result", f"{float(summary.get('net_r', 0)):.2f}R")
    st.caption(
        f"{report.get('strategy', 'AMD-Structure Entry Model')} · {report.get('symbol', '—')} "
        f"{report.get('timeframe', '—')} · {report.get('sample_start', '—')} to {report.get('sample_end', '—')}"
    )
    if trades.empty:
        st.info("No trade-level records were produced.")
        return
    columns = [column for column in [
        "signal.session_date", "signal.direction", "signal.quality_score", "signal.entry_price",
        "signal.stop_price", "signal.target_price", "outcome", "realised_r", "maximum_favourable_r",
        "maximum_adverse_r", "entry_time", "exit_time"
    ] if column in trades]
    st.dataframe(trades[columns].sort_values("signal.session_date", ascending=False), use_container_width=True, hide_index=True)
