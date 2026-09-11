"""Restart-safe idempotency and agent-run outcome ledger."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Admission:
    admitted: bool
    reason: str
    attempts: int


class RunLedger:
    def __init__(self, path: Path | str):
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(self.path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA busy_timeout=5000")
        self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS runs (
                event_id TEXT PRIMARY KEY,
                route TEXT NOT NULL,
                event_type TEXT NOT NULL,
                status TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 1,
                received_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                error TEXT NOT NULL DEFAULT '',
                payload_json TEXT NOT NULL DEFAULT '{}'
            )
            """
        )
        self._db.execute(
            "CREATE INDEX IF NOT EXISTS runs_status_updated ON runs(status, updated_at)"
        )
        self._db.commit()

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def admit(
        self,
        event_id: str,
        *,
        route: str,
        event_type: str,
        payload: Any,
        stale_after: float,
        max_attempts: int = 10,
        now: float | None = None,
    ) -> Admission:
        now = time.time() if now is None else now
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        with self._lock, self._db:
            row = self._db.execute(
                "SELECT status, attempts, updated_at FROM runs WHERE event_id = ?", (event_id,)
            ).fetchone()
            if row is None:
                self._db.execute(
                    "INSERT INTO runs(event_id, route, event_type, status, received_at, "
                    "updated_at, payload_json) VALUES (?, ?, ?, 'running', ?, ?, ?)",
                    (event_id, route, event_type, now, now, encoded),
                )
                return Admission(True, "new", 1)
            attempts = int(row["attempts"])
            status = str(row["status"])
            if status == "succeeded":
                return Admission(False, "already_succeeded", attempts)
            if status == "running" and now - float(row["updated_at"]) < stale_after:
                return Admission(False, "already_running", attempts)
            if attempts >= max_attempts:
                self._db.execute(
                    "UPDATE runs SET status='dead', updated_at=? WHERE event_id=?",
                    (now, event_id),
                )
                return Admission(False, "attempts_exhausted", attempts)
            attempts += 1
            self._db.execute(
                "UPDATE runs SET status='running', attempts=?, updated_at=?, error='', "
                "payload_json=? WHERE event_id=?",
                (attempts, now, encoded, event_id),
            )
            return Admission(True, "retry", attempts)

    def finish(self, event_id: str, *, success: bool, error: str = "") -> None:
        with self._lock, self._db:
            self._db.execute(
                "UPDATE runs SET status=?, error=?, updated_at=? WHERE event_id=?",
                ("succeeded" if success else "failed", error[:2000], time.time(), event_id),
            )

    def stats(self) -> dict[str, int]:
        with self._lock:
            rows = self._db.execute(
                "SELECT status, COUNT(*) count FROM runs GROUP BY status"
            ).fetchall()
        return {str(row["status"]): int(row["count"]) for row in rows}

    def failures(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._db.execute(
                "SELECT event_id, route, event_type, status, attempts, updated_at, error "
                "FROM runs WHERE status IN ('failed','dead') ORDER BY updated_at DESC LIMIT ?",
                (max(1, min(limit, 100)),),
            ).fetchall()
        return [dict(row) for row in rows]

    def get(self, event_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM runs WHERE event_id=?", (event_id,)
            ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["payload"] = json.loads(result.pop("payload_json"))
        return result

    def reset(self, event_id: str) -> bool:
        with self._lock, self._db:
            cursor = self._db.execute(
                "UPDATE runs SET status='failed', attempts=0, error='', updated_at=? "
                "WHERE event_id=?",
                (time.time(), event_id),
            )
            return cursor.rowcount > 0
