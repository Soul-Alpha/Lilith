from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from .backtest import AMDStructureBacktester, summarize
from .engine import AMDStructureEngine
from .models import AMDStructureConfig, BacktestTrade


def _dataset_hash(candles: pd.DataFrame) -> str:
    canonical = candles.to_csv(index=False, lineterminator="\n").encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _config_payload(config: AMDStructureConfig) -> dict[str, Any]:
    payload = asdict(config)
    for key, value in tuple(payload.items()):
        if hasattr(value, "isoformat"):
            payload[key] = value.isoformat()
    return payload


class JaxterResearchRunner:
    """Runs isolated historical research and persists immutable evidence runs."""

    def __init__(self, config: AMDStructureConfig | None = None) -> None:
        self.config = config or AMDStructureConfig()
        self.engine = AMDStructureEngine(self.config)
        self.backtester = AMDStructureBacktester(self.config)

    def run(
        self,
        candles: pd.DataFrame,
        *,
        symbol: str = "XAUUSD",
        timeframe: str = "M5",
        lookback_months: int = 6,
        source_name: str | None = None,
    ) -> tuple[list[BacktestTrade], dict[str, Any]]:
        if lookback_months not in {3, 4, 5, 6}:
            raise ValueError("lookback_months must be between 3 and 6")
        required = {"timestamp", "open", "high", "low", "close"}
        missing = required.difference(candles.columns)
        if missing:
            raise ValueError(f"Missing candle columns: {sorted(missing)}")
        timestamps = pd.to_datetime(candles["timestamp"], utc=True, errors="raise")
        if timestamps.empty:
            raise ValueError("CSV contains no candles")
        end = timestamps.max()
        start = end - pd.DateOffset(months=lookback_months)
        sample = candles.loc[timestamps >= start].copy()
        if sample.empty:
            raise ValueError("No candles fall inside the requested lookback window")
        data_hash = _dataset_hash(sample)
        config = _config_payload(self.config)
        config_hash = hashlib.sha256(json.dumps(config, sort_keys=True).encode("utf-8")).hexdigest()
        created_at = datetime.now(timezone.utc)
        run_seed = f"{self.config.strategy_version}|{symbol}|{timeframe}|{created_at.isoformat()}|{data_hash}|{config_hash}"
        run_id = hashlib.sha256(run_seed.encode("utf-8")).hexdigest()[:24]
        signals = self.engine.scan(sample, symbol=symbol, timeframe=timeframe)
        trades = self.backtester.evaluate(sample, signals)
        report: dict[str, Any] = {
            "schema_version": "jaxter-research-v2",
            "run_id": run_id,
            "created_at": created_at.isoformat(),
            "engine": "Jaxter",
            "strategy": "AMD-Structure Entry Model",
            "strategy_version": self.config.strategy_version,
            "symbol": symbol,
            "timeframe": timeframe,
            "lookback_months": lookback_months,
            "sample_start": start.isoformat(),
            "sample_end": end.isoformat(),
            "candle_count": len(sample),
            "source_name": source_name,
            "dataset_sha256": data_hash,
            "configuration": config,
            "configuration_sha256": config_hash,
            "entry_eligibility": "strictly_after_bos_close",
            "same_bar_ambiguity_policy": "stop_first",
            "observational_only": True,
            "execution_authorized": False,
            "risk_fraction_research_assumption": self.config.risk_fraction,
            "summary": summarize(trades),
        }
        return trades, report

    @staticmethod
    def persist(
        trades: list[BacktestTrade],
        report: dict[str, Any],
        output_dir: str | Path = "data/jaxter",
    ) -> Path:
        directory = Path(output_dir)
        run_id = str(report.get("run_id", "")).strip()
        if not run_id:
            raise ValueError("report must contain run_id")
        run_directory = directory / "runs" / run_id
        run_directory.mkdir(parents=True, exist_ok=False)
        report_path = run_directory / "report.json"
        trades_path = run_directory / "trades.jsonl"
        report_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
        with trades_path.open("x", encoding="utf-8") as handle:
            for trade in trades:
                payload = {"run_id": run_id, **trade.to_dict()}
                handle.write(json.dumps(payload, sort_keys=True, default=str) + "\n")

        directory.mkdir(parents=True, exist_ok=True)
        latest_report = directory / "amd_structure_report.json"
        latest_trades = directory / "amd_structure_trades.jsonl"
        report_tmp = latest_report.with_suffix(".json.tmp")
        trades_tmp = latest_trades.with_suffix(".jsonl.tmp")
        report_tmp.write_text(report_path.read_text(encoding="utf-8"), encoding="utf-8")
        trades_tmp.write_text(trades_path.read_text(encoding="utf-8"), encoding="utf-8")
        report_tmp.replace(latest_report)
        trades_tmp.replace(latest_trades)
        return run_directory
