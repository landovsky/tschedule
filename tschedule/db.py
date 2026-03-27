"""SQLite persistence for job registry and run history."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id          INTEGER PRIMARY KEY,
    project     TEXT NOT NULL,
    name        TEXT NOT NULL,
    description TEXT DEFAULT '',
    tags        TEXT DEFAULT '[]',
    UNIQUE(project, name)
);

CREATE TABLE IF NOT EXISTS runs (
    id          INTEGER PRIMARY KEY,
    job_id      INTEGER NOT NULL REFERENCES jobs(id),
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    exit_code   INTEGER,
    stdout      TEXT,
    stderr      TEXT
);

CREATE INDEX IF NOT EXISTS idx_runs_job_id ON runs(job_id);
CREATE INDEX IF NOT EXISTS idx_runs_started_at ON runs(started_at);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


class DB:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._init()

    def _init(self):
        with self._conn() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # --- Job registry ---

    def upsert_job(self, project: str, name: str, description: str, tags: list) -> int:
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO jobs (project, name, description, tags) VALUES (?, ?, ?, ?)
                   ON CONFLICT(project, name) DO UPDATE SET
                       description = excluded.description,
                       tags = excluded.tags""",
                (project, name, description, json.dumps(tags)),
            )
            row = conn.execute(
                "SELECT id FROM jobs WHERE project=? AND name=?", (project, name)
            ).fetchone()
            return row['id']

    def get_job_id(self, project: str, name: str) -> int | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT id FROM jobs WHERE project=? AND name=?", (project, name)
            ).fetchone()
            return row['id'] if row else None

    # --- Run recording ---

    def start_run(self, job_id: int) -> int:
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO runs (job_id, started_at) VALUES (?, ?)",
                (job_id, _now()),
            )
            return cur.lastrowid

    def finish_run(self, run_id: int, exit_code: int, stdout: str, stderr: str):
        with self._conn() as conn:
            conn.execute(
                "UPDATE runs SET finished_at=?, exit_code=?, stdout=?, stderr=? WHERE id=?",
                (_now(), exit_code, stdout, stderr, run_id),
            )

    # --- Queries ---

    def get_run_history(self, job_id: int, limit: int = 20) -> list:
        with self._conn() as conn:
            return conn.execute(
                "SELECT * FROM runs WHERE job_id=? ORDER BY started_at DESC LIMIT ?",
                (job_id, limit),
            ).fetchall()

    def get_all_jobs_with_stats(self) -> list:
        with self._conn() as conn:
            return conn.execute("""
                SELECT
                    j.*,
                    r.started_at  AS last_run,
                    r.finished_at AS last_finished,
                    r.exit_code   AS last_exit_code,
                    (SELECT COUNT(*) FROM runs r2
                     WHERE r2.job_id = j.id
                       AND r2.exit_code != 0
                       AND r2.started_at > datetime('now', '-7 days')) AS errors_7d,
                    (SELECT COUNT(*) FROM runs r3 WHERE r3.job_id = j.id) AS total_runs
                FROM jobs j
                LEFT JOIN runs r ON r.id = (
                    SELECT id FROM runs WHERE job_id = j.id
                    ORDER BY started_at DESC LIMIT 1
                )
                ORDER BY j.project, j.name
            """).fetchall()

    def get_all_runs(self, limit: int = 500) -> list:
        with self._conn() as conn:
            return conn.execute("""
                SELECT r.*, j.project, j.name AS job_name, j.tags
                FROM runs r
                JOIN jobs j ON j.id = r.job_id
                ORDER BY r.started_at DESC
                LIMIT ?
            """, (limit,)).fetchall()
