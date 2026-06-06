"""Owner notifications + durable event log (FR-13, FR-15).

`log_event` persists every alarm-relevant event (timestamp, zone, level, the stage-2
assessment, and the actions taken) to a local SQLite store for audit (FR-15). It is on the
**always-runs** path: it must work with no network and must never block or gate the alarm
(ICD-6). `notify` (owner push, FR-13) and the offline queue/flush land in M6.

STATUS: M2 — log_event() implemented (SQLite audit store). notify() is M6.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from autosentry.config import NotifyConfig
from autosentry.contracts import ThreatAssessment, ThreatState

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          REAL    NOT NULL,
    zone        TEXT    NOT NULL,
    level       TEXT    NOT NULL,
    reason      TEXT    NOT NULL,
    assessment  TEXT,
    actions     TEXT    NOT NULL
)
"""


class Notifier:
    """Best-effort owner notifications backed by a durable local audit store."""

    def __init__(self, config: NotifyConfig) -> None:
        self.cfg = config
        self._db: sqlite3.Connection | None = None

    def _connect(self) -> sqlite3.Connection:
        if self._db is None:
            self._db = sqlite3.connect(self.cfg.queue_path)
            self._db.execute(_SCHEMA)
            self._db.commit()
        return self._db

    def log_event(
        self,
        state: ThreatState,
        assessment: ThreatAssessment | None,
        actions: list[str],
    ) -> None:
        """Persist an auditable event row (FR-15). Always runs, even with no network."""
        db = self._connect()
        db.execute(
            "INSERT INTO events (ts, zone, level, reason, assessment, actions) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                state.since,
                state.zone,
                state.level.value,
                state.reason,
                assessment.model_dump_json() if assessment is not None else None,
                json.dumps(actions),
            ),
        )
        db.commit()

    def events(self) -> list[dict[str, Any]]:
        """Read back logged events (audit/tests)."""
        db = self._connect()
        cols = ["id", "ts", "zone", "level", "reason", "assessment", "actions"]
        rows = db.execute(f"SELECT {', '.join(cols)} FROM events ORDER BY id").fetchall()
        return [dict(zip(cols, row, strict=True)) for row in rows]

    def close(self) -> None:
        if self._db is not None:
            self._db.close()
            self._db = None

    def notify(self, state: ThreatState, assessment: ThreatAssessment | None) -> None:
        """Enqueue an owner push; send now if online, else flush later (FR-13, OS-5)."""
        raise NotImplementedError("Notifier.notify lands in M6 (see docs/ROADMAP.md)")
