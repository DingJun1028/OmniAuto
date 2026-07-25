"""Provenance log + job store (IDEA.md module 7).

Default: local SQLite (jobs.db). If NCBDB_BASE_URL + NCBDB_TOKEN are
set, lifecycle events are additionally mirrored to NoCodeBackend via HTTP.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx

from .config import BASE_DIR, NCBDB_BASE_URL, NCBDB_TOKEN, USE_NCBDB

DB_PATH = BASE_DIR / "jobs.db"


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                job_id      TEXT PRIMARY KEY,
                title       TEXT,
                status      TEXT,
                progress    INTEGER DEFAULT 0,
                payload     TEXT,
                result      TEXT,
                file        TEXT,
                created_at  TEXT,
                updated_at  TEXT
            )
            """
        )


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_job(job_id: str, title: str, payload: dict) -> dict:
    ts = now_iso()
    with _conn() as conn:
        conn.execute(
            "INSERT INTO jobs (job_id, title, status, progress, payload, created_at, updated_at) "
            "VALUES (?, ?, 'queued', 0, ?, ?, ?)",
            (job_id, title, json.dumps(payload, ensure_ascii=False), ts, ts),
        )
    _log_provenance(job_id, "created", {"title": title})
    return get_job(job_id)  # type: ignore[return-value]


def update_job(job_id: str, **fields) -> Optional[dict]:
    fields["updated_at"] = now_iso()
    cols = ", ".join(f"{k}=?" for k in fields)
    vals = list(fields.values())
    vals.append(job_id)
    with _conn() as conn:
        conn.execute(f"UPDATE jobs SET {cols} WHERE job_id=?", vals)
    if "status" in fields:
        _log_provenance(job_id, fields["status"], fields)
    return get_job(job_id)


def get_job(job_id: str) -> Optional[dict]:
    with _conn() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
    return dict(row) if row else None


def list_jobs(limit: int = 50) -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def _log_provenance(job_id: str, event: str, data: dict) -> None:
    """Mirror a lifecycle event to NoCodeBackend if configured (IDEA.md 5T)."""
    if not USE_NCBDB:
        return
    payload = {
        "uuid": job_id,
        "timestamp": now_iso(),
        "event": event,
        "meta": data,
    }
    try:
        httpx.post(
            f"{NCBDB_BASE_URL.rstrip('/')}/records",
            json=payload,
            headers={"Authorization": f"Bearer {NCBDB_TOKEN}"},
            timeout=10,
        )
    except Exception:
        # Provenance is best-effort; never break the pipeline on a log failure.
        pass
