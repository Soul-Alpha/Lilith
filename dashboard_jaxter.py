from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd
import streamlit as st

from lilith.jaxter import AMDStructureConfig, JaxterResearchRunner

REPORT_PATH = Path(os.getenv("JAXTER_AMD_REPORT_PATH", "data/jaxter/amd_structure_report.json"))
TRADES_PATH = Path(os.getenv("JAXTER_AMD_TRADES_PATH", "data/jaxter/amd_structure_trades.jsonl"))
OUTPUT_DIR = Path(os.getenv("JAXTER_OUTPUT_DIR", "data/jaxter"))
_REQUIRED_COLUMNS = ("timestamp", "open", "high", "low", "close")


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


def _format_metric(value: object, suffix: str = "") -> str:
    if value is None:
        return "Awaiting"
    return f"{float(value):.2f}{suffix}"


def _validate_upload(frame: pd.DataFrame) -> pd.DataFrame:
    missing = [column for column in _REQUIRED_COLUMNS if column not in frame.columns]
    if missing:
        raise ValueError(f"Missing required CSV columns: {missing}")
    clean = frame.loc[:, list(_REQUIRED_COLUMNS)].copy()
    clean["timestamp"] = pd.to_datetime(clean["timestamp"], utc=True, errors="raise")
    for column in ("open", "high", "low", "close"):
        clean[column] = pd.to_numeric(clean[column], errors="raise")
    clean = clean.sort_values("timestamp").drop_duplicates("timestamp", keep="last").reset_index(drop=True)
    if clean.empty:
        raise ValueError("CSV contains no usable candles")
    invalid = (
        (clean["high"] < clean[["open", "close"]].max(axis=1))
        | (clean["low"] > clean[["open", "close"]].min(axis=1))
        | (clean["high"] < clean["low"])
    )
    if invalid.any():
        raise ValueError(f"CSV contains {int(invalid.sum())} invalid OHLC candles")
    return clean


def _render_upload_panel() -> None:
    with st.expander("Run a new Jaxter historical study", expanded=not REPORT_PATH.exists()):
        st.write("Upload completed XAUUSD M5 or M15 candles covering at least the selected 3–6 month window.")
        st.code("timestamp,open,high,low,close")
        uploaded = st.file_uploader("Upload OHLC CSV", type=["csv"], key="jaxter_amd_csv")
        first, second, third, fourth = st.columns(4)
        symbol = first.text_input("Symbol", value="XAUUSD", key="jaxter_symbol")
        timeframe = second.selectbox("Timeframe", options=("M5", "M15"), key="jaxter_timeframe")
        months = third.selectbox("Lookback months", options=(3, 4, 5, 6), index=3, key="jaxter_months")
        risk_percent = fourth.selectbox("Research risk", options=(0.5, 0.75, 1.0), index=0, key="jaxter_risk")

        if uploaded is None:
            st.caption("No CSV selected. Existing Jaxter evidence remains unchanged.")
            return
        try:
            preview = _validate_upload(pd.read_csv(uploaded))
        except (OSError, UnicodeDecodeError, pd.errors.ParserError, ValueError) as exc:
            st.error(f"CSV validation failed: {exc}")
            return

        start, end = preview["timestamp"].min(), preview["timestamp"].max()
        span_days = max(0, int((end - start).total_seconds() // 86400))
        st.success(f"Validated {len(preview):,} candles from {start} to {end} ({span_days:,} days).")
        st.dataframe(preview.head(10), use_container_width=True, hide_index=True)

        if st.button("Run AMD-Structure research", type="primary", key="jaxter_run_research"):
            try:
                runner = JaxterResearchRunner(AMDStructureConfig(risk_fraction=risk_percent / 100.0))
                trades, report = runner.run(
                    preview,
                    symbol=symbol.strip() or "XAUUSD",
                    timeframe=timeframe,
                    lookback_months=int(months),
                    source_name=uploaded.name,
                )
                run_directory = runner.persist(trades, report, OUTPUT_DIR)
            except (OSError, ValueError) as exc:
                st.error(f"Jaxter research failed: {exc}")
                return
            st.success(f"Research run {report['run_id']} completed and preserved at {run_directory}.")
            st.rerun()


def render_jaxter_dashboard() -> None:
    st.divider()
    st.header("Jaxter · Strategy Assistant")
    st.caption("Isolated research engine. Jaxter cannot place orders, alter Edith, or authorize execution.")
    _render_upload_panel()

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
    win_rate = summary.get("win_rate")
    c.metric("Win rate", "Awaiting" if win_rate is None else f"{float(win_rate) * 100:.1f}%")
    d.metric("Expectancy", _format_metric(summary.get("expectancy_r"), "R"))
    e.metric("Net result", _format_metric(summary.get("net_r"), "R"))
    st.caption(
        f"Run {report.get('run_id', 'legacy')} · {report.get('strategy', 'AMD-Structure Entry Model')} · "
        f"{report.get('symbol', '—')} {report.get('timeframe', '—')} · "
        f"{report.get('sample_start', '—')} to {report.get('sample_end', '—')}"
    )
    if trades.empty:
        st.info("No trade-level records were produced.")
        return
    columns = [column for column in [
        "signal.session_date", "signal.direction", "signal.quality_score", "signal.entry_price",
        "signal.stop_price", "signal.target_price", "outcome", "realised_r", "maximum_favourable_r",
        "maximum_adverse_r", "entry_time", "exit_time"
    ] if column in trades]
    if not columns or "signal.session_date" not in trades:
        st.warning("Trade evidence exists but does not match the current Jaxter schema.")
        return
    st.dataframe(trades[columns].sort_values("signal.session_date", ascending=False), use_container_width=True, hide_index=True)
