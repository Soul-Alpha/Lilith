from __future__ import annotations

import json
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path
from typing import Iterable

from .models import FeatureCombinationResult


def write_results_jsonl(
    results: Iterable[FeatureCombinationResult],
    path: str | Path = "data/feature_sculptor_results.jsonl",
) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8") as handle:
        for result in results:
            payload = asdict(result)
            payload["expectancy_pnl"] = str(result.expectancy_pnl)
            payload["expectancy_r"] = str(result.expectancy_r)
            payload["profit_factor"] = str(result.profit_factor)
            payload["max_drawdown"] = str(result.max_drawdown)
            payload["feature_names"] = list(result.feature_names)
            payload["feature_values"] = list(result.feature_values)
            payload["rejection_reasons"] = list(result.rejection_reasons)
            handle.write(json.dumps(payload, sort_keys=True) + "\n")
    return destination
