from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from enum import Enum
import json
from pathlib import Path
import sqlite3
from typing import Any, Callable, Iterable, Mapping


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, tuple):
        return list(value)
    raise TypeError(f"unsupported report value: {type(value)!r}")


class InstitutionalReportStore:
    """Append-only persistence for execution, portfolio, quality and learning reports."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS institutional_reports (
                    report_id TEXT PRIMARY KEY,
                    report_type TEXT NOT NULL,
                    subject_id TEXT NOT NULL,
                    version TEXT NOT NULL,
                    generated_at_utc TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_report_subject ON institutional_reports(report_type, subject_id)"
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def append(
        self,
        *,
        report_id: str,
        report_type: str,
        subject_id: str,
        version: str,
        report: Any,
        generated_at_utc: datetime | None = None,
    ) -> None:
        generated = generated_at_utc or datetime.now(timezone.utc)
        if generated.tzinfo is None:
            raise ValueError("report timestamp must be timezone-aware")
        payload = json.dumps(report, default=_json_default, sort_keys=True, separators=(",", ":"))
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO institutional_reports (
                    report_id, report_type, subject_id, version, generated_at_utc, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (report_id, report_type, subject_id, version, generated.astimezone(timezone.utc).isoformat(), payload),
            )

    def records(self, *, report_type: str | None = None, subject_id: str | None = None) -> list[dict[str, Any]]:
        with self._connect() as connection:
            if report_type is not None and subject_id is not None:
                rows = connection.execute(
                    "SELECT * FROM institutional_reports WHERE report_type = ? AND subject_id = ? ORDER BY generated_at_utc, report_id",
                    (report_type, subject_id),
                ).fetchall()
            elif report_type is not None:
                rows = connection.execute(
                    "SELECT * FROM institutional_reports WHERE report_type = ? ORDER BY generated_at_utc, report_id",
                    (report_type,),
                ).fetchall()
            elif subject_id is not None:
                rows = connection.execute(
                    "SELECT * FROM institutional_reports WHERE subject_id = ? ORDER BY generated_at_utc, report_id",
                    (subject_id,),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM institutional_reports ORDER BY generated_at_utc, report_id"
                ).fetchall()
        return [
            {
                "report_id": row["report_id"],
                "report_type": row["report_type"],
                "subject_id": row["subject_id"],
                "version": row["version"],
                "generated_at_utc": row["generated_at_utc"],
                "payload": json.loads(row["payload_json"]),
            }
            for row in rows
        ]


class BackfillCheckpointStore:
    """Tracks deterministic source checkpoints without altering source systems."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS backfill_checkpoints (
                    source_name TEXT PRIMARY KEY,
                    cursor_value TEXT NOT NULL,
                    updated_at_utc TEXT NOT NULL,
                    processed_count INTEGER NOT NULL,
                    rejected_count INTEGER NOT NULL
                )
                """
            )

    def save(self, source_name: str, cursor_value: str, *, processed_count: int, rejected_count: int) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                """
                INSERT INTO backfill_checkpoints VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(source_name) DO UPDATE SET
                    cursor_value=excluded.cursor_value,
                    updated_at_utc=excluded.updated_at_utc,
                    processed_count=excluded.processed_count,
                    rejected_count=excluded.rejected_count
                """,
                (source_name, cursor_value, now, processed_count, rejected_count),
            )

    def load(self, source_name: str) -> dict[str, Any] | None:
        with sqlite3.connect(self.path) as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute(
                "SELECT * FROM backfill_checkpoints WHERE source_name = ?", (source_name,)
            ).fetchone()
        return dict(row) if row is not None else None


class InstitutionalBatchRunner:
    """Runs explicit, restart-safe analytical batches with rejection accounting."""

    def run(
        self,
        records: Iterable[Any],
        processor: Callable[[Any], Any],
        *,
        identity: Callable[[Any], str],
    ) -> dict[str, Any]:
        processed: list[Any] = []
        rejected: list[dict[str, str]] = []
        seen: set[str] = set()
        duplicates = 0
        for record in records:
            record_id = identity(record)
            if record_id in seen:
                duplicates += 1
                continue
            seen.add(record_id)
            try:
                processed.append(processor(record))
            except (ValueError, TypeError, KeyError) as exc:
                rejected.append({"record_id": record_id, "error": str(exc)})
        return {
            "processed": processed,
            "processed_count": len(processed),
            "rejected": rejected,
            "rejected_count": len(rejected),
            "duplicate_count": duplicates,
            "source_count": len(seen) + duplicates,
        }


def operational_health_snapshot(
    *,
    observations: int,
    execution_reports: int,
    portfolio_reports: int,
    learning_reviews: int,
    rejected_records: int,
    last_success_utc: datetime | None,
) -> Mapping[str, Any]:
    total_outputs = observations + execution_reports + portfolio_reports + learning_reviews
    rejection_ratio = rejected_records / max(total_outputs + rejected_records, 1)
    freshness_hours = None
    if last_success_utc is not None:
        if last_success_utc.tzinfo is None:
            raise ValueError("last success timestamp must be timezone-aware")
        freshness_hours = max(
            (datetime.now(timezone.utc) - last_success_utc.astimezone(timezone.utc)).total_seconds() / 3600.0,
            0.0,
        )
    healthy = total_outputs > 0 and rejection_ratio <= 0.05 and (freshness_hours is None or freshness_hours <= 48.0)
    return {
        "healthy": healthy,
        "total_outputs": total_outputs,
        "rejection_ratio": rejection_ratio,
        "freshness_hours": freshness_hours,
        "observations": observations,
        "execution_reports": execution_reports,
        "portfolio_reports": portfolio_reports,
        "learning_reviews": learning_reviews,
    }
