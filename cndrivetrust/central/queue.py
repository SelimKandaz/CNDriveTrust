"""Persistent sender queue; test disposition never depends on delivery."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from drive_evidence import utc_now


class SyncQueue:
    def __init__(self, database: Path):
        self.database = database

    def initialize(self) -> None:
        self.database.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS sync_runs(
                sync_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, kind TEXT NOT NULL, serial TEXT NOT NULL,
                batch_id TEXT NOT NULL, run_dir TEXT NOT NULL, bundle_path TEXT NOT NULL,
                bundle_sha256 TEXT NOT NULL, state TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
                last_error TEXT NOT NULL DEFAULT '', acknowledgement TEXT NOT NULL DEFAULT '',
                created_utc TEXT NOT NULL, updated_utc TEXT NOT NULL)""")
            db.execute("UPDATE sync_runs SET state='SYNC_PENDING',last_error='previous sync interrupted' WHERE state='SYNC_IN_PROGRESS'")

    def enqueue(self, *, run_id: str, kind: str, serial: str, batch_id: str, run_dir: Path,
                bundle_path: Path, bundle_sha256: str) -> str:
        self.initialize()
        now = utc_now()
        sync_id = f"{run_id}\0{serial}"
        with self.connection() as db:
            row = db.execute("SELECT bundle_sha256,state FROM sync_runs WHERE sync_id=?", (sync_id,)).fetchone()
            if row:
                if row[0] != bundle_sha256:
                    raise ValueError("RUN_ID_CONFLICT")
                return str(row[1])
            db.execute("INSERT INTO sync_runs VALUES(?,?,?,?,?,?,?,?,'SYNC_PENDING',0,'','',?,?)",
                       (sync_id, run_id, kind, serial, batch_id, str(run_dir), str(bundle_path), bundle_sha256, now, now))
        return "SYNC_PENDING"

    def pending(self, limit: int = 20) -> list[dict[str, Any]]:
        self.initialize()
        with self.connection() as db:
            db.row_factory = sqlite3.Row
            return [dict(row) for row in db.execute(
                "SELECT * FROM sync_runs WHERE state IN ('SYNC_PENDING','SYNC_FAILED_RETRYABLE') ORDER BY created_utc LIMIT ?",
                (max(1, min(limit, 100)),))]

    def mark(self, sync_id: str, state: str, *, error: str = "", acknowledgement: dict[str, Any] | None = None) -> None:
        with self.connection() as db:
            db.execute("UPDATE sync_runs SET state=?,attempts=attempts+?,last_error=?,acknowledgement=?,updated_utc=? WHERE sync_id=?",
                       (state, 1 if state == "SYNC_IN_PROGRESS" else 0, error[:500],
                        json.dumps(acknowledgement, sort_keys=True) if acknowledgement else "", utc_now(), sync_id))

    def status(self) -> dict[str, Any]:
        self.initialize()
        with self.connection() as db:
            counts = {row[0]: row[1] for row in db.execute("SELECT state,count(*) FROM sync_runs GROUP BY state")}
            last = db.execute("SELECT run_id,state,updated_utc,last_error FROM sync_runs ORDER BY updated_utc DESC LIMIT 1").fetchone()
        return {"counts": counts, "pending": sum(counts.get(x, 0) for x in ("SYNC_PENDING", "SYNC_FAILED_RETRYABLE")),
                "last": dict(zip(("run_id", "state", "updated_utc", "last_error"), last)) if last else None}

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.database, timeout=30)
        db.execute("PRAGMA journal_mode=WAL")
        try:
            with db:
                yield db
        finally:
            db.close()
