"""Tests for n8n workflow JSON validation (§23 §24 automation)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
N8N_DIR = ROOT / "n8n"


def _load_workflow(name: str) -> dict:
    p = N8N_DIR / f"{name}.json"
    assert p.exists(), f"Workflow not found: {p}"
    return json.loads(p.read_text(encoding="utf-8"))


def test_weekly_swarm_report_workflow_valid():
    """weekly-swarm-report.json is valid JSON with expected structure."""
    wf = _load_workflow("weekly-swarm-report")
    assert "name" in wf
    assert "nodes" in wf
    assert "connections" in wf
    assert len(wf["nodes"]) >= 2  # schedule + exec at minimum


def test_weekly_swarm_report_has_schedule_trigger():
    """Workflow must have a scheduleTrigger node set to weekly (Monday 09:00)."""
    wf = _load_workflow("weekly-swarm-report")
    schedule_nodes = [
        n for n in wf["nodes"]
        if n.get("type") == "n8n-nodes-base.scheduleTrigger"
    ]
    assert len(schedule_nodes) == 1
    rule = schedule_nodes[0]["parameters"]["rule"]
    intervals = rule["interval"]
    assert any(i.get("weeksInterval") == 1 for i in intervals), "must run weekly"
    assert any(i.get("weekdays") == [1] for i in intervals), "must run on Monday"
    assert any(i.get("hoursInterval") == 9 for i in intervals), "must run at hour 9"


def test_weekly_swarm_report_has_execute_command():
    """Workflow must have an executeCommand node calling weekly_report.py."""
    wf = _load_workflow("weekly-swarm-report")
    exec_nodes = [
        n for n in wf["nodes"]
        if n.get("type") == "n8n-nodes-base.executeCommand"
    ]
    assert len(exec_nodes) == 1
    assert "weekly_report.py" in exec_nodes[0]["parameters"]["command"]


def test_weekly_swarm_report_connections():
    """Schedule node must connect to the exec node."""
    wf = _load_workflow("weekly-swarm-report")
    conns = wf["connections"]
    schedule_name = "每週一 09:00"
    assert schedule_name in conns
    assert "main" in conns[schedule_name]
    assert len(conns[schedule_name]["main"][0]) == 1
    assert conns[schedule_name]["main"][0][0]["node"] == "生成並發送週報"


def test_weekly_swarm_report_v2_valid():
    """weekly-swarm-report-v2.json is valid JSON with improved structure."""
    wf = _load_workflow("weekly-swarm-report-v2")
    assert "name" in wf
    assert "nodes" in wf
    assert "connections" in wf
    assert len(wf["nodes"]) >= 4  # schedule + audit + exec + if + alert


def test_ai_station_workflow_valid():
    """workflow.json is valid JSON with expected structure."""
    wf = _load_workflow("workflow")
    assert "name" in wf
    assert "nodes" in wf
    assert "connections" in wf
    assert len(wf["nodes"]) >= 3  # schedule + http + if/notify


def test_ai_station_workflow_has_webhook():
    """AI Station workflow must POST to the n8n webhook."""
    wf = _load_workflow("workflow")
    http_nodes = [
        n for n in wf["nodes"]
        if n.get("type") == "n8n-nodes-base.httpRequest"
    ]
    assert len(http_nodes) == 1
    assert "webhook" in http_nodes[0]["parameters"]["url"].lower() or "aistation" in http_nodes[0]["parameters"]["url"].lower()


def test_ai_station_workflow_has_condition():
    """AI Station workflow must have an if-condition checking for 'done' status."""
    wf = _load_workflow("workflow")
    if_nodes = [
        n for n in wf["nodes"]
        if n.get("type") == "n8n-nodes-base.if"
    ]
    assert len(if_nodes) == 1
    rule = if_nodes[0]["parameters"]["conditions"]["rules"]
    found = any(
        r.get("value1", "").startswith("={{ ") and "status" in r.get("value1", "")
        for r in rule
    )
    assert found, "Must check $json.status"
