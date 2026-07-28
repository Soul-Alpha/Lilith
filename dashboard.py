from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

st.set_page_config(page_title="Edith Command Centre", page_icon="🧠", layout="wide")

DATA_PATH = Path(os.environ.get("EDITH_FORENSICS_PATH", "data/forensic_reports.jsonl"))


def load_reports(path: Path) -> pd.DataFrame:
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
    return f"R {value:,.2f}"


st.title("Edith Command Centre")
st.caption("Read-only forensic intelligence. Trading and broker execution remain disabled in this interface.")

with st.sidebar:
    st.subheader("Data source")
    st.code(str(DATA_PATH))
    st.write("Execution mode:", os.environ.get("LILITH_EXECUTION_MODE", "simulation"))
    refresh = st.button("Refresh data", use_container_width=True)

if refresh:
    st.cache_data.clear()

try:
    reports = load_reports(DATA_PATH)
except (OSError, ValueError) as exc:
    st.error(f"Unable to load forensic records: {exc}")
    st.stop()

if reports.empty:
    st.info(
        "Awaiting forensic records. Configure EDITH_FORENSICS_PATH or write JSON Lines records to "
        "data/forensic_reports.jsonl. No example trading performance is fabricated."
    )
    st.stop()

for column in ("net_realised_pnl", "r_multiple", "mfe_r", "mae_r", "peak_floating_pnl", "trough_floating_pnl"):
    if column in reports:
        reports[column] = pd.to_numeric(reports[column], errors="coerce")

net_pnl = float(reports.get("net_realised_pnl", pd.Series(dtype=float)).fillna(0).sum())
trade_count = len(reports)
wins = int((reports.get("net_realised_pnl", pd.Series(dtype=float)).fillna(0) > 0).sum())
win_rate = wins / trade_count * 100 if trade_count else 0.0
avg_r = float(reports.get("r_multiple", pd.Series(dtype=float)).dropna().mean() or 0.0)
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
    st.subheader("Cumulative realised performance")
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
    "trade_id",
    "exit_reason",
    "net_realised_pnl",
    "r_multiple",
    "mfe_r",
    "mae_r",
    "direction_quality",
    "entry_quality",
    "stop_quality",
    "target_quality",
    "management_quality",
    "primary_cause",
]
visible = [column for column in forensic_columns if column in reports.columns]
st.dataframe(reports[visible], use_container_width=True, hide_index=True)

st.subheader("Primary causes")
if "primary_cause" in reports:
    st.bar_chart(reports["primary_cause"].value_counts())

with st.expander("Record contract"):
    st.write(
        "Each line in the configured JSONL file should contain one completed TradeForensicReport plus optional "
        "exit_timestamp, symbol, timeframe, session and regime fields. Decimal values should be serialized as numbers or strings."
    )
