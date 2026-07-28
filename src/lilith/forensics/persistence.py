from __future__ import annotations

import json
from dataclasses import asdict
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any, Mapping

from .models import TradeForensicReport


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    return value


def report_record(report: TradeForensicReport, **context: Any) -> dict[str, Any]:
    record = {key: _json_value(value) for key, value in asdict(report).items()}
    record.update({key: _json_value(value) for key, value in context.items()})
    return record


def append_report_jsonl(
    report: TradeForensicReport,
    path: str | Path = "data/forensic_reports.jsonl",
    **context: Any,
) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    record = report_record(report, **context)
    with destination.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True, separators=(",", ":")))
        handle.write("\n")
    return destination
