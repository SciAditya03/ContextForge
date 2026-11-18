"""SQLite persistence (local-first). Thread-safe via a lock; WAL mode for concurrent readers."""

from __future__ import annotations

import contextlib
import json
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    archive_name TEXT,
    archive_size INTEGER,
    options TEXT NOT NULL DEFAULT '{}',
    stats TEXT NOT NULL DEFAULT '{}',
    error TEXT,
    fingerprint TEXT
);
CREATE TABLE IF NOT EXISTS project_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_project ON project_events(project_id, id);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(SCHEMA)
        with contextlib.suppress(OSError):
            path.chmod(0o600)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ------------------------------------------------------------- projects
    def create_project(self, pid: str, name: str, description: str | None, archive_name: str, archive_size: int, options: dict[str, Any]) -> None:
        ts = now()
        with self._lock:
            self._conn.execute(
                "INSERT INTO projects (id, name, description, status, created_at, updated_at, archive_name, archive_size, options) VALUES (?,?,?,?,?,?,?,?,?)",
                (pid, name, description, "queued", ts, ts, archive_name, archive_size, json.dumps(options)),
            )

    def update_project(self, pid: str, **fields: Any) -> None:
        if not fields:
            return
        allowed = {"status", "stats", "error", "fingerprint", "options", "name", "description"}
        sets, vals = [], []
        for k, v in fields.items():
            if k not in allowed:
                raise ValueError(f"cannot update {k}")
            sets.append(f"{k} = ?")
            vals.append(json.dumps(v) if k in ("stats", "options") else v)
        sets.append("updated_at = ?")
        vals.append(now())
        vals.append(pid)
        with self._lock:
            self._conn.execute(f"UPDATE projects SET {', '.join(sets)} WHERE id = ?", vals)  # noqa: S608 - column names are allow-listed

    def get_project(self, pid: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM projects WHERE id = ?", (pid,)).fetchone()
        return _row(row) if row else None

    def list_projects(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM projects ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [_row(r) for r in rows]

    def delete_project(self, pid: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM project_events WHERE project_id = ?", (pid,))
            self._conn.execute("DELETE FROM projects WHERE id = ?", (pid,))

    def mark_interrupted(self) -> int:
        """Projects left running by a previous process cannot resume: mark them failed."""
        with self._lock:
            cur = self._conn.execute(
                "UPDATE projects SET status = 'failed', error = 'Analysis interrupted by a server restart', updated_at = ? WHERE status IN ('queued', 'running')",
                (now(),),
            )
            return cur.rowcount

    # ------------------------------------------------------------- events
    def add_event(self, pid: str, payload: dict[str, Any]) -> int:
        with self._lock:
            cur = self._conn.execute("INSERT INTO project_events (project_id, created_at, payload) VALUES (?,?,?)", (pid, now(), json.dumps(payload)))
            return int(cur.lastrowid or 0)

    def events(self, pid: str, after: int = 0) -> list[tuple[int, dict[str, Any]]]:
        with self._lock:
            rows = self._conn.execute("SELECT id, payload FROM project_events WHERE project_id = ? AND id > ? ORDER BY id", (pid, after)).fetchall()
        return [(int(r["id"]), json.loads(r["payload"])) for r in rows]

    # ------------------------------------------------------------- settings
    def get_setting(self, key: str) -> Any:
        with self._lock:
            row = self._conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return json.loads(row["value"]) if row else None

    def set_setting(self, key: str, value: Any) -> None:
        with self._lock:
            self._conn.execute("INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, json.dumps(value)))


def _row(r: sqlite3.Row) -> dict[str, Any]:
    d = dict(r)
    for k in ("options", "stats"):
        try:
            d[k] = json.loads(d.get(k) or "{}")
        except ValueError:
            d[k] = {}
    return d
