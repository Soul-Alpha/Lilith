from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import streamlit as st


DAILY_RISK_PATH = Path(
    os.getenv("EDITH_DAILY_RISK_LATEST_PATH", "data/portfolio/latest_daily_risk.json")
)


def _load_snapshot() -> dict[str, Any]:
    if not DAILY_RISK_PATH.exists():
        return {}
    payload = json.loads(DAILY_RISK_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("daily risk snapshot must contain a JSON object")
    return payload


def _number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _money(value: Any, currency: str) -> str:
    number = _number(value)
    return "Awaiting" if number is None else f"{currency} {number:,.2f}"


def _r(value: Any) -> str:
    number = _number(value)
    return "Awaiting" if number is None else f"{number:.2f}R"


def _age_minutes(value: Any) -> float | None:
    if not value:
        return None
    try:
        generated = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if generated.tzinfo is None:
        generated = generated.replace(tzinfo=timezone.utc)
    return max(
        (datetime.now(timezone.utc) - generated.astimezone(timezone.utc)).total_seconds() / 60.0,
        0.0,
    )


def render_portfolio_dashboard() -> None:
    st.divider()
    st.header("Portfolio Intelligence · Daily Risk Ledger")
    st.caption(
        "Advisory daily capital evidence. This ledger cannot change signals, position size, orders, or execution."
    )

    try:
        snapshot = _load_snapshot()
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        st.error(f"Unable to load daily portfolio risk evidence: {exc}")
        return

    if not snapshot:
        st.info("Awaiting the first reconciled daily risk snapshot.")
        st.code(str(DAILY_RISK_PATH))
        return

    currency = str(snapshot.get("currency") or "USD")
    evidence_complete = bool(snapshot.get("evidence_complete"))
    age = _age_minutes(snapshot.get("generated_at_utc"))
    age_text = "unknown age" if age is None else f"{age:.1f} minutes old"

    if evidence_complete:
        st.success(f"Daily risk evidence complete · {age_text}")
    else:
        st.warning(f"Daily risk evidence incomplete — remaining risk is not authoritative · {age_text}")

    first = st.columns(6)
    first[0].metric("Daily budget", _money(snapshot.get("daily_budget_cash"), currency))
    first[1].metric("Realised PnL", _money(snapshot.get("realised_net_pnl_cash"), currency))
    first[2].metric("Realised losses", _money(snapshot.get("realised_loss_cash"), currency))
    first[3].metric("Open stop-risk", _money(snapshot.get("open_risk_cash"), currency))
    first[4].metric("Risk consumed", _money(snapshot.get("consumed_risk_cash"), currency))
    first[5].metric("Risk remaining", _money(snapshot.get("remaining_risk_cash"), currency))

    second = st.columns(6)
    second[0].metric("Budget", _r(snapshot.get("daily_budget_r")))
    second[1].metric("Losses", _r(snapshot.get("realised_loss_r")))
    second[2].metric("Open heat", _r(snapshot.get("open_portfolio_heat_r")))
    second[3].metric("Consumed", _r(snapshot.get("consumed_risk_r")))
    second[4].metric("Remaining", _r(snapshot.get("remaining_risk_r")))
    second[5].metric("Floating PnL", _money(snapshot.get("open_floating_pnl_cash"), currency))

    third = st.columns(4)
    third[0].metric("Closed trades today", f"{int(snapshot.get('trade_count', 0)):,}")
    third[1].metric("Open positions", f"{int(snapshot.get('open_position_count', 0)):,}")
    third[2].metric("Current loss streak", f"{int(snapshot.get('consecutive_losses', 0)):,}")
    third[3].metric("External cash flows", _money(snapshot.get("excluded_cash_flow_cash"), currency))

    st.caption(
        f"Trading date: {snapshot.get('trading_date', '—')} · "
        f"Policy: {snapshot.get('policy_version', '—')} · "
        f"Report: {snapshot.get('report_id', '—')} · Advisory only"
    )

    reasons = snapshot.get("evidence_reasons") or []
    with st.expander("Evidence lineage and reconciliation"):
        if reasons:
            st.subheader("Outstanding evidence")
            for reason in reasons:
                st.write(f"• {reason}")
        else:
            st.write("No reconciliation exceptions recorded.")
        st.write("Configuration hash:", snapshot.get("configuration_hash", "—"))
        source_ids = snapshot.get("source_record_ids") or []
        st.write(f"Source records: {len(source_ids):,}")
        if source_ids:
            st.code("\n".join(str(value) for value in source_ids[-50:]))
