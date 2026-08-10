"""KPI 儀表板 (Chapter 10 best-practice dashboard).

Aggregates OA-Team swarm KPIs and the AI Station pipeline metrics into a
single snapshot with threshold checks. Used by the weekly swarm report and
the newsletter module. Free-local: reads from the SQLite job store in `db`
plus an in-memory KPI ledger; no external services.

Threshold model (from soul canon §十 10.6):
  cross_unit_pairing >= 100%, handoff_time < 2h, defect_rate < 1%,
  idea_realization >= 80%, satisfaction > 4.5/5, security_events == 0,
  entropy < 0.1, ai_station_success >= 95%.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

from . import db, metrics

# Default targets from the soul canon KPI matrix (§十 10.6).
DEFAULT_TARGETS = {
    "cross_unit_pairing": 100.0,   # %
    "handoff_time": 2.0,           # hours (lower better)
    "defect_rate": 1.0,            # % (lower better)
    "idea_realization": 80.0,      # %
    "satisfaction": 4.5,           # /5 (higher better)
    "security_events": 0,          # count (lower better)
    "entropy": 0.1,                # (lower better)
    "ai_station_success": 95.0,    # %
}


@dataclass
class KpiSnapshot:
    values: Dict[str, float] = field(default_factory=dict)
    targets: Dict[str, float] = field(default_factory=dict)
    alerts: List[Dict[str, str]] = field(default_factory=list)

    def status(self, key: str) -> str:
        """Return OK / WARN / CRIT based on distance to target."""
        v = self.values.get(key)
        t = self.targets.get(key)
        if v is None or t is None:
            return "N/A"
        # lower-is-better keys
        if key in ("handoff_time", "defect_rate", "security_events", "entropy"):
            ratio = v / t if t else (0.0 if v == 0 else 9.9)
        else:
            ratio = t / v if v else 9.9
        if ratio <= 1.0:
            return "OK"
        if ratio <= 1.15:
            return "WARN"
        return "CRIT"

    @property
    def overall(self) -> str:
        order = {"OK": 0, "WARN": 1, "CRIT": 2, "N/A": 0}
        worst = max((order[self.status(k)] for k in self.values), default=0)
        return ["OK", "WARN", "CRIT"][worst]


def snapshot(targets: Dict[str, float] | None = None, **overrides) -> KpiSnapshot:
    """Build a KPI snapshot.

    Pipeline-derived KPIs (ai_station_success, avg_render) come from
    `metrics.compute_metrics()`; swarm KPIs come from `overrides` (callers
    feed real measured values — never fabricated). Missing swarm KPIs are
    omitted rather than invented.
    """
    tgt = dict(DEFAULT_TARGETS)
    if targets:
        tgt.update(targets)

    m = metrics.compute_metrics()
    success = m.get("success_rate")
    values: Dict[str, float] = {}
    if success is not None:
        values["ai_station_success"] = float(success)
    if m.get("avg_render_seconds") is not None:
        values["avg_render_seconds"] = float(m["avg_render_seconds"])

    # Swarm KPIs — only if the caller supplies real measurements.
    for k in ("cross_unit_pairing", "handoff_time", "defect_rate",
              "idea_realization", "satisfaction", "security_events", "entropy"):
        if k in overrides:
            values[k] = float(overrides[k])

    snap = KpiSnapshot(values=values, targets=tgt)
    for k in values:
        st = snap.status(k)
        if st in ("WARN", "CRIT"):
            snap.alerts.append({
                "level": "CRIT" if st == "CRIT" else "WARN",
                "metric": k,
                "value": str(values[k]),
                "target": str(tgt.get(k)),
            })
    return snap


def render_text(snap: KpiSnapshot) -> str:
    """Plain-text dashboard for terminal / newsletter."""
    lines = [f"KPI 儀表板 — 總評: {snap.overall}"]
    for k in snap.values:
        lines.append(f"  {k:22s} {snap.values[k]:>10}  [{snap.status(k)}]")
    if snap.alerts:
        lines.append("告警:")
        for a in snap.alerts:
            lines.append(f"  [{a['level']}] {a['metric']} = {a['value']} (目標 {a['target']})")
    return "\n".join(lines)
