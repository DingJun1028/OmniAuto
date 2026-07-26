"""Observability — lightweight job metrics (TODO pillar 6 enhancement).

Read-only aggregations over the job store so the dashboard can show
throughput, reliability, and per-brand activity without any external
dependency. All numbers are computed on demand from the SQLite store
in `db`, so it works on the free local path with no extra setup.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone

from . import db
from .config import log


def _parse_ts(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return None


def compute_metrics(limit: int = 500) -> dict:
    """Aggregate a snapshot of pipeline health from recent jobs.

    Returns a dict with lifecycle-complete numbers:
      total, by_status, success_rate, avg_render_seconds,
      top_brands, last_24h_count, brand_breakdown.
    """
    jobs = db.list_jobs(limit)
    total = len(jobs)
    if total == 0:
        return {
            "total": 0,
            "by_status": {},
            "success_rate": None,
            "avg_render_seconds": None,
            "top_brands": [],
            "last_24h_count": 0,
            "brand_breakdown": {},
        }

    by_status = Counter(j["status"] for j in jobs)
    done = by_status.get("done", 0)
    failed = by_status.get("failed", 0)
    finished = done + failed
    success_rate = round(100.0 * done / finished, 1) if finished else None

    # avg render seconds: created -> updated for jobs that reached a terminal
    # state (best-effort wall-clock proxy; no dedicated duration column).
    durations = []
    now = datetime.now(timezone.utc)
    day_ago = now.timestamp() - 24 * 3600
    last_24h = 0
    for j in jobs:
        c = _parse_ts(j.get("created_at"))
        u = _parse_ts(j.get("updated_at"))
        if c and u:
            d = (u - c).total_seconds()
            if d >= 0 and j["status"] in ("done", "failed"):
                durations.append(d)
        if c and c.timestamp() >= day_ago:
            last_24h += 1

    avg_render_seconds = round(sum(durations) / len(durations), 1) if durations else None

    # brand breakdown from payload (free path stores brand_preset=None,
    # DNA scripts infer the brand from the preset at submit time).
    brands: Counter = Counter()
    for j in jobs:
        try:
            payload = j.get("payload")
            p = payload if isinstance(payload, dict) else __loads(payload)
            brand = (p or {}).get("brand_preset") or "default"
        except Exception:
            brand = "default"
        brands[brand] += 1
    top_brands = brands.most_common(5)

    return {
        "total": total,
        "by_status": dict(by_status),
        "success_rate": success_rate,
        "avg_render_seconds": avg_render_seconds,
        "top_brands": [{"brand": b, "count": n} for b, n in top_brands],
        "last_24h_count": last_24h,
        "brand_breakdown": dict(brands),
    }


def __loads(s):
    import json

    try:
        return json.loads(s) if s else {}
    except Exception:
        log.warning("metrics: bad payload json for a job")
        return {}
