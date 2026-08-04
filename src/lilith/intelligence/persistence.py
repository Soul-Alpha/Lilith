from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Iterable

from .models import Observation


class ObservationStore:
    """Append-only SQLite store for Edith-native institutional observations."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialise()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialise(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS observations (
                    record_id TEXT PRIMARY KEY,
                    timestamp_utc TEXT NOT NULL,
                    instrument TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    evidence_stage TEXT NOT NULL,
                    outcome_status TEXT NOT NULL,
                    r_multiple REAL,
                    payload_json TEXT NOT NULL,
                    created_at_utc TEXT NOT NULL
                )
                """
            )
            connection.execute("CREATE INDEX IF NOT EXISTS idx_observation_time ON observations(timestamp_utc)")
            connection.execute("CREATE INDEX IF NOT EXISTS idx_observation_fingerprint ON observations(fingerprint)")

    def append(self, observation: Observation) -> None:
        payload = observation.to_dict()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO observations (
                    record_id, timestamp_utc, instrument, timeframe, fingerprint,
                    evidence_stage, outcome_status, r_multiple, payload_json, created_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    observation.record_id,
                    payload["timestamp_utc"],
                    observation.instrument,
                    observation.timeframe,
                    observation.market_state.fingerprint(),
                    observation.evidence_stage.value,
                    observation.outcome.status,
                    observation.outcome.r_multiple,
                    json.dumps(payload, sort_keys=True, separators=(",", ":")),
                    payload["metadata"]["created_at_utc"],
                ),
            )

    def append_many(self, observations: Iterable[Observation]) -> int:
        count = 0
        for observation in observations:
            self.append(observation)
            count += 1
        return count

    def records(self, *, instrument: str | None = None, timeframe: str | None = None) -> list[dict]:
        with self._connect() as connection:
            if instrument is not None and timeframe is not None:
                rows = connection.execute(
                    "SELECT payload_json FROM observations WHERE instrument = ? AND timeframe = ? ORDER BY timestamp_utc, record_id",
                    (instrument, timeframe),
                ).fetchall()
            elif instrument is not None:
                rows = connection.execute(
                    "SELECT payload_json FROM observations WHERE instrument = ? ORDER BY timestamp_utc, record_id",
                    (instrument,),
                ).fetchall()
            elif timeframe is not None:
                rows = connection.execute(
                    "SELECT payload_json FROM observations WHERE timeframe = ? ORDER BY timestamp_utc, record_id",
                    (timeframe,),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT payload_json FROM observations ORDER BY timestamp_utc, record_id"
                ).fetchall()
        return [json.loads(row["payload_json"]) for row in rows]

    def count(self) -> int:
        with self._connect() as connection:
            return int(connection.execute("SELECT COUNT(*) FROM observations").fetchone()[0])
