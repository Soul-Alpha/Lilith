from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

STATE_PATH = Path(os.getenv("EDITH_ADAPTATION_STATE_PATH", "data/adaptation_state.json"))
EVENTS_PATH = Path(os.getenv("EDITH_ADAPTATION_EVENTS_PATH", "data/adaptation_events.jsonl"))


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _load_events(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"{path} line {number} must contain a JSON object")
            state = value.get("state", {})
            candidate = value.get("candidate", {})
            decision = value.get("decision", {})
            evidence = value.get("evidence", {})
            rows.append(
                {
                    "recorded_at_utc": value.get("recorded_at_utc"),
                    "sequence": state.get("sequence"),
                    "stage": state.get("stage"),
                    "action": decision.get("action"),
                    "active_version": state.get("active_version"),
                    "previous_version": state.get("previous_version"),
                    "challenger_version": candidate.get("challenger_version"),
                    "allocation_percent": float(state.get("allocation_fraction", 0.0) or 0.0) * 100,
                    "sample_size": evidence.get("sample_size"),
                    "expectancy_r": evidence.get("expectancy_r"),
                    "drawdown_percent": float(evidence.get("drawdown_percent", 0.0) or 0.0) * 100,
                    "reasons": ", ".join(decision.get("reasons", [])),
                    "audit_digest": decision.get("audit_digest"),
                }
            )
    return pd.DataFrame(rows)


def _pct(value: Any) -> str:
    try:
        return f"{float(value) * 100:.1f}%"
    except (TypeError, ValueError):
        return "0.0%"


def _r(value: Any) -> str:
    try:
        return f"{float(value):+.2f}R"
    except (TypeError, ValueError):
        return "+0.00R"


def render_adaptation_dashboard() -> None:
    st.divider()
    st.header("Autonomous Live Adaptation")
    st.caption("Fail-closed champion–challenger observability. Runtime activation remains bounded by manifest, governance, data-quality and portfolio-risk gates.")

    try:
        snapshot = _load_json(STATE_PATH)
        events = _load_events(EVENTS_PATH)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        st.error(f"Unable to load autonomous adaptation telemetry: {exc}")
        return

    if not snapshot:
        st.info(
            "Awaiting adaptation telemetry. The controller is available, but the host runtime has not yet written "
            f"a snapshot to {STATE_PATH}."
        )
        with st.expander("Expected telemetry files"):
            st.code(str(STATE_PATH))
            st.code(str(EVENTS_PATH))
        return

    state = snapshot.get("state", {})
    candidate = snapshot.get("candidate", {})
    evidence = snapshot.get("evidence", {})
    policy = snapshot.get("policy", {})
    decision = snapshot.get("decision", {})
    quality = snapshot.get("quality", {})
    recommendation = snapshot.get("recommendation", {})
    guardrails = snapshot.get("guardrails", {})

    stage = str(state.get("stage", "UNKNOWN"))
    enabled = bool(policy.get("enabled", False))
    kill_switch = bool(snapshot.get("kill_switch", False))
    if stage in {"ROLLED_BACK", "HALTED"} or kill_switch:
        st.error(f"Adaptation state: {stage} — {', '.join(decision.get('reasons', [])) or 'guardrail intervention'}")
    elif stage == "CANARY":
        st.warning(f"Canary active at {_pct(state.get('allocation_fraction'))}. Guardrails are continuously evaluated.")
    elif stage == "LIVE":
        st.success("Challenger promoted to live champion and currently within recorded guardrails.")
    elif stage == "SHADOW":
        st.info("Challenger is in shadow evaluation with zero live allocation.")
    else:
        st.info(f"Autonomous adaptation is {'enabled' if enabled else 'disabled'}; current stage is {stage}.")

    a, b, c, d, e, f = st.columns(6)
    a.metric("Adaptation", "Enabled" if enabled else "Disabled")
    b.metric("Stage", stage)
    c.metric("Champion", str(candidate.get("champion_version", state.get("previous_version", "—"))))
    d.metric("Challenger", str(candidate.get("challenger_version", "—")))
    e.metric("Active version", str(state.get("active_version", "—")))
    f.metric("Allocation", _pct(state.get("allocation_fraction")))

    g, h, i, j, k, l = st.columns(6)
    g.metric("Samples", f"{int(evidence.get('sample_size', 0) or 0):,}")
    h.metric("Challenger expectancy", _r(evidence.get("expectancy_r")))
    i.metric("Champion expectancy", _r(evidence.get("champion_expectancy_r")))
    j.metric("Improvement", _r(snapshot.get("expectancy_improvement_r")))
    k.metric("Drawdown", _pct(evidence.get("drawdown_percent")))
    l.metric("Portfolio heat", _pct(evidence.get("portfolio_heat")))

    st.subheader("Lifecycle progress")
    lifecycle = ["SHADOW", "CANARY", "LIVE"]
    current_index = lifecycle.index(stage) if stage in lifecycle else -1
    cols = st.columns(3)
    sample_size = int(evidence.get("sample_size", 0) or 0)
    shadow_required = int(policy.get("minimum_shadow_samples", 100) or 100)
    canary_required = int(policy.get("minimum_canary_samples", 50) or 50)
    labels = [
        ("Shadow", sample_size, shadow_required, current_index >= 0),
        ("Canary", sample_size, canary_required, current_index >= 1),
        ("Live", 1 if stage == "LIVE" else 0, 1, stage == "LIVE"),
    ]
    for column, (label, value, required, reached) in zip(cols, labels):
        with column:
            st.markdown(f"**{label}**")
            st.progress(min(value / max(required, 1), 1.0))
            st.caption(f"{value:,} / {required:,} · {'reached' if reached else 'pending'}")

    left, right = st.columns([1.15, 1])
    with left:
        st.subheader("Champion versus challenger")
        comparison = pd.DataFrame(
            [
                {"Metric": "Expectancy", "Champion": _r(evidence.get("champion_expectancy_r")), "Challenger": _r(evidence.get("expectancy_r")), "Policy": f"≥ {_r(policy.get('minimum_expectancy_improvement_r'))} improvement"},
                {"Metric": "Drawdown", "Champion": "—", "Challenger": _pct(evidence.get("drawdown_percent")), "Policy": f"≤ {_pct(policy.get('maximum_drawdown_percent'))}"},
                {"Metric": "Drift", "Champion": "—", "Challenger": f"{float(evidence.get('drift_score', 0.0) or 0.0):.3f}", "Policy": f"≤ {float(policy.get('maximum_drift_score', 0.0) or 0.0):.3f}"},
                {"Metric": "Loss streak", "Champion": "—", "Challenger": int(evidence.get("loss_streak", 0) or 0), "Policy": f"≤ {int(policy.get('maximum_loss_streak', 0) or 0)}"},
                {"Metric": "Portfolio heat", "Champion": "—", "Challenger": _pct(evidence.get("portfolio_heat")), "Policy": f"≤ {_pct(policy.get('maximum_portfolio_heat'))}"},
                {"Metric": "Data quality", "Champion": "—", "Challenger": _pct(quality.get("score")), "Policy": f"≥ {_pct(policy.get('minimum_quality_score'))}"},
                {"Metric": "Recommendation", "Champion": "—", "Challenger": _pct(recommendation.get("score")), "Policy": f"≥ {_pct(policy.get('minimum_recommendation_score'))}"},
            ]
        )
        st.dataframe(comparison, use_container_width=True, hide_index=True)

    with right:
        st.subheader("Guardrails")
        if guardrails:
            rows = [{"Gate": key.replace("_", " ").title(), "Status": "PASS" if passed else "FAIL"} for key, passed in guardrails.items()]
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        else:
            st.info("No guardrail evaluation recorded.")

    rollback_col, audit_col = st.columns([1, 2])
    with rollback_col:
        st.subheader("Rollback readiness")
        st.metric("Previous champion", str(state.get("previous_version", "—")))
        st.metric("Kill switch", "ACTIVE" if kill_switch else "Clear")
        st.metric("Fatal runtime errors", f"{int(evidence.get('fatal_errors', 0) or 0):,}")
        st.caption(f"Last action: {decision.get('action', '—')}")
        st.caption(f"Sequence: {int(state.get('sequence', 0) or 0):,}")
        digest = str(decision.get("audit_digest", ""))
        if digest:
            st.code(digest, language=None)

    with audit_col:
        st.subheader("Adaptation audit timeline")
        if events.empty:
            st.info("No append-only adaptation events recorded yet.")
        else:
            display = events.tail(25).iloc[::-1].copy()
            if "recorded_at_utc" in display:
                display["recorded_at_utc"] = pd.to_datetime(display["recorded_at_utc"], errors="coerce", utc=True)
            st.dataframe(display, use_container_width=True, hide_index=True)

    st.caption(
        f"Last telemetry: {snapshot.get('recorded_at_utc', '—')} · Candidate: {candidate.get('candidate_id', '—')} · "
        f"Manifest: {str(candidate.get('manifest_digest', '—'))[:16]}… · Telemetry: {str(snapshot.get('telemetry_digest', '—'))[:16]}…"
    )
