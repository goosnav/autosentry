"""Owner notifications + durable event log (FR-13, FR-15).

`log_event` persists every alarm-relevant event (timestamp, zone, level, the stage-2
assessment, the actions taken, and the on-disk keyframe paths) to a local SQLite store for
audit (FR-15). The keyframe images themselves are encoded upstream (`notify/keyframes.py`,
best-effort); this store only records their paths. It is on the
**always-runs** path: it must work with no network and must never block or gate the alarm
(ICD-6). `notify` (owner push, FR-13) queues to a durable outbox and `flush` drains it when
the network returns (OS-5) — both best-effort and strictly off the critical path (pillar 1).

STATUS: M6 — log_event() (M2) + notify()/flush() durable owner-push queue.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from typing import Any, Protocol

from autosentry.config import NotifyConfig
from autosentry.contracts import Notification, ThreatAssessment, ThreatState

log = logging.getLogger("autosentry.notify")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          REAL    NOT NULL,
    zone        TEXT    NOT NULL,
    level       TEXT    NOT NULL,
    reason      TEXT    NOT NULL,
    assessment  TEXT,
    actions     TEXT    NOT NULL,
    keyframes   TEXT    NOT NULL DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS outbox (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          REAL    NOT NULL,
    zone        TEXT    NOT NULL,
    level       TEXT    NOT NULL,
    summary     TEXT    NOT NULL,
    sent        INTEGER NOT NULL DEFAULT 0
)
"""


class NotifySender(Protocol):
    """Delivers one notification to the owner; raises if offline/unreachable."""

    def send(self, note: Notification) -> None: ...


class Notifier:
    """Best-effort owner notifications backed by a durable local audit store."""

    def __init__(self, config: NotifyConfig, sender: NotifySender | None = None) -> None:
        self.cfg = config
        self._db: sqlite3.Connection | None = None
        self._sender = sender

    def _connect(self) -> sqlite3.Connection:
        if self._db is None:
            self._db = sqlite3.connect(self.cfg.queue_path)
            self._db.executescript(_SCHEMA)
            self._db.commit()
        return self._db

    def log_event(
        self,
        state: ThreatState,
        assessment: ThreatAssessment | None,
        actions: list[str],
        keyframes: list[str] | None = None,
    ) -> None:
        """Persist an auditable event row (FR-15). Always runs, even with no network.

        `keyframes` is the list of on-disk image paths captured for this event (the
        triggering frame). It is metadata only — the heavy image encoding happens upstream
        and is best-effort, so a failed capture still yields a complete audit row.
        """
        db = self._connect()
        db.execute(
            "INSERT INTO events (ts, zone, level, reason, assessment, actions, keyframes) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                state.since,
                state.zone,
                state.level.value,
                state.reason,
                assessment.model_dump_json() if assessment is not None else None,
                json.dumps(actions),
                json.dumps(keyframes or []),
            ),
        )
        db.commit()

    _EVENT_COLS = ("id", "ts", "zone", "level", "reason", "assessment", "actions", "keyframes")

    def events(self) -> list[dict[str, Any]]:
        """Read back all logged events oldest-first (audit/tests)."""
        db = self._connect()
        cols = self._EVENT_COLS
        rows = db.execute(f"SELECT {', '.join(cols)} FROM events ORDER BY id").fetchall()
        return [dict(zip(cols, row, strict=True)) for row in rows]

    def recent_events(self, limit: int) -> list[dict[str, Any]]:
        """The newest `limit` events, newest-first — bounded by SQL, not in Python.

        The dashboard polls this frequently; pushing ORDER BY + LIMIT into SQLite means a
        months-old store with thousands of rows never loads the whole table into memory
        (an unbounded read on every refresh otherwise).
        """
        db = self._connect()
        cols = self._EVENT_COLS
        rows = db.execute(
            f"SELECT {', '.join(cols)} FROM events ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(zip(cols, row, strict=True)) for row in rows]

    def close(self) -> None:
        if self._db is not None:
            self._db.close()
            self._db = None

    def notify(self, state: ThreatState, assessment: ThreatAssessment | None) -> None:
        """Enqueue an owner push, then try to flush; if offline it stays queued (FR-13, OS-5).

        Persisting first means a notification survives a crash or an internet outage and is
        delivered when the link returns — the alarm never waits on it (pillar 1, ICD-6).
        """
        db = self._connect()
        summary = assessment.description if assessment is not None else state.reason
        db.execute(
            "INSERT INTO outbox (ts, zone, level, summary, sent) VALUES (?, ?, ?, ?, 0)",
            (state.since, state.zone, state.level.value, summary),
        )
        db.commit()
        self.flush()

    def flush(self) -> int:
        """Drain queued notifications oldest-first; stop at the first failure (still offline).

        Returns the number delivered this pass. A send failure leaves that row and all later
        rows queued so ordering is preserved and nothing is dropped (OS-5).
        """
        if not self.cfg.enabled:
            return 0
        try:
            sender = self._ensure_sender()
        except Exception as e:
            log.warning("no notification sender available: %s", e)
            return 0
        db = self._connect()
        rows = db.execute(
            "SELECT id, ts, zone, level, summary FROM outbox WHERE sent = 0 ORDER BY id"
        ).fetchall()
        delivered = 0
        for row_id, ts, zone, level, summary in rows:
            note = Notification(
                event_id=row_id, zone=zone, ts=ts, threat_level=level, assessment_summary=summary
            )
            try:
                sender.send(note)
            except Exception as e:  # offline/unreachable — keep this + the rest queued
                log.warning("notification flush stopped (offline?): %s", e)
                break
            db.execute("UPDATE outbox SET sent = 1 WHERE id = ?", (row_id,))
            db.commit()
            delivered += 1
        return delivered

    def pending(self) -> int:
        """Count of notifications still queued for delivery (audit/tests)."""
        db = self._connect()
        return int(db.execute("SELECT COUNT(*) FROM outbox WHERE sent = 0").fetchone()[0])

    def _ensure_sender(self) -> NotifySender:
        if self._sender is None:
            from autosentry.notify.sender import HttpNotifySender

            self._sender = HttpNotifySender(self.cfg)
        return self._sender
