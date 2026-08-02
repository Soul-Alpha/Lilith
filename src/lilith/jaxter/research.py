from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pandas as pd

from .backtest import AMDStructureBacktester, summarize
from .engine import AMDStructureEngine
from .models import AMDStructureConfig, BacktestTrade


class JaxterResearchRunner:
    """Runs isolated historical research and persists additive evidence only."""

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
    ) -> tuple[list[BacktestTrade], dict[str, Any]]:
        if lookback_months not in {3, 4, 5, 6}:
            raise ValueError("lookback_months must be between 3 and 6")
        timestamps = pd.to_datetime(candles["timestamp"], utc=True, errors="raise")
        end = timestamps.max()
        start = end - pd.DateOffset(months=lookback_months)
        sample = candles.loc[timestamps >= start].copy()
        signals = self.engine.scan(sample, symbol=symbol, timeframe=timeframe)
        trades = self.backtester.evaluate(sample, signals)
        report: dict[str, Any] = {
            "engine": "Jaxter",
            "strategy": "AMD-Structure Entry Model",
            "strategy_version": self.config.strategy_version,
            "symbol": symbol,
            "timeframe": timeframe,
            "lookback_months": lookback_months,
            "sample_start": start.isoformat(),
            "sample_end": end.isoformat(),
            "candle_count": len(sample),
            "observational_only": True,
            "execution_authorized": False,
            "risk_fraction_research_assumption": self.config.risk_fraction,
            "summary": summarize(trades),
        }
        return trades, report

    @staticmethod
    def persist(trades: list[BacktestTrade], report: dict[str, Any], output_dir: str | Path = "data/jaxter") -> None:
        directory = Path(output_dir)
        directory.mkdir(parents=True, exist_ok=True)
        report_path = directory / "amd_structure_report.json"
        trades_path = directory / "amd_structure_trades.jsonl"
        temporary = report_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
        temporary.replace(report_path)
        with trades_path.open("w", encoding="utf-8") as handle:
            for trade in trades:
                handle.write(json.dumps(trade.to_dict(), sort_keys=True, default=str) + "\n")
