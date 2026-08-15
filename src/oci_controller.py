"""OCI Controller: REST API for managing OCI instances.
Integrates with AI Station pipeline as optional step #8 (infrastructure control).
5T: Traceable (instance ops logged), Trackable (status changes), Trustworthy (locked responses).
"""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/oci", tags=["oci"])

# ---- config ----
OCI_BIN = "/home/ubuntu/bin/oci"
COMPARTMENT = "ocid1.tenancy.oc1..aaaaaaaadof5rgb76zexk24q6fnhopqjnrqaxwmeuxunoynw46g3lj3lfnlq"
REGION = "ap-singapore-1"
INSTANCES_FILE = Path("/tmp/oci_instances_cache.json")
OPS_LOG = Path("/tmp/oci_ops.log")


def _log_op(action: str, instance: str, result: str) -> None:
    """Trackable: append operation to append-only log."""
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "instance": instance,
        "result": result,
    }
    OPS_LOG.parent.mkdir(parents=True, exist_ok=True)
    with OPS_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _oci(cmd: list[str], timeout: int = 30) -> dict:
    """Trustworthy: run oci with locked env, return parsed JSON or raise."""
    env = {**os.environ, "SUPPRESS_LABEL_WARNING": "true"}
    try:
        proc = subprocess.run(
            [OCI_BIN, *cmd],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
            check=False,
        )
    except FileNotFoundError:
        raise HTTPException(500, "oci binary not found")
    except subprocess.TimeoutExpired:
        raise HTTPException(504, "oci command timed out")

    if proc.returncode != 0:
        raise HTTPException(502, detail=f"oci error: {proc.stderr.strip()[:300]}")

    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {"raw": proc.stdout.strip()}


# ---- models ----
class InstanceInfo(BaseModel):
    name: str
    state: str
    shape: str
    ocpus: float | None = None
    memory_gb: float | None = None
    region: str
    public_ip: str | None = None
    private_ip: str | None = None


class ActionRequest(BaseModel):
    instance: str = Field(..., description="instance display-name")
    preserve_boot_volume: bool = True


class ActionResponse(BaseModel):
    action: str
    instance: str
    status: str
    timestamp: str


# ---- endpoints ----
@router.get("/instances", response_model=list[InstanceInfo])
def list_instances() -> list[InstanceInfo]:
    """Traceable: list all compute instances in compartment."""
    data = _oci([
        "compute", "instance", "list",
        "--compartment-id", COMPARTMENT,
        "--region", REGION,
        "--output", "json",
    ])
    out = []
    for item in data.get("data", []):
        out.append(InstanceInfo(
            name=item.get("display-name", ""),
            state=item.get("lifecycle-state", ""),
            shape=item.get("shape", ""),
            ocpus=item.get("shape-config", {}).get("ocpus"),
            memory_gb=item.get("shape-config", {}).get("memory-in-gbs"),
            region=item.get("region", ""),
            public_ip=item.get("public-ip"),
            private_ip=item.get("private-ip"),
        ))
    # Trustworthy: freeze cached list
    INSTANCES_FILE.write_text(json.dumps([i.dict() for i in out], ensure_ascii=False))
    _log_op("list", "*", f"count={len(out)}")
    return out


@router.get("/instances/{name}", response_model=InstanceInfo)
def get_instance(name: str) -> InstanceInfo:
    """Trackable: get single instance details."""
    data = _oci([
        "compute", "instance", "get",
        "--compartment-id", COMPARTMENT,
        "--region", REGION,
        "--instance-name", name,
        "--output", "json",
    ])
    item = data.get("data", {})
    return InstanceInfo(
        name=item.get("display-name", name),
        state=item.get("lifecycle-state", ""),
        shape=item.get("shape", ""),
        ocpus=item.get("shape-config", {}).get("ocpus"),
        memory_gb=item.get("shape-config", {}).get("memory-in-gbs"),
        region=item.get("region", ""),
        public_ip=item.get("public-ip"),
        private_ip=item.get("private-ip"),
    )


@router.post("/instances/{name}/start", response_model=ActionResponse)
def start_instance(name: str) -> ActionResponse:
    """Start a stopped instance."""
    _oci([
        "compute", "instance", "action", "start",
        "--compartment-id", COMPARTMENT,
        "--region", REGION,
        "--instance-name", name,
    ])
    _log_op("start", name, "ok")
    return ActionResponse(
        action="start", instance=name, status="started",
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


@router.post("/instances/{name}/stop", response_model=ActionResponse)
def stop_instance(name: str, body: ActionRequest | None = None) -> ActionResponse:
    """Stop an instance (preserve boot volume by default)."""
    preserve = True if body is None else body.preserve_boot_volume
    cmd = [
        "compute", "instance", "action", "stop",
        "--compartment-id", COMPARTMENT,
        "--region", REGION,
        "--instance-name", name,
    ]
    if preserve:
        cmd += ["--preserve-boot-volume", "true"]
    _oci(cmd)
    _log_op("stop", name, f"preserve={preserve}")
    return ActionResponse(
        action="stop", instance=name, status="stopped",
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


@router.get("/ops-log")
def read_ops_log(limit: int = 50) -> list[dict]:
    """Transparent: read recent OCI operations."""
    if not OPS_LOG.exists():
        return []
    lines = OPS_LOG.read_text(encoding="utf-8").strip().split("\n")
    entries = [json.loads(l) for l in lines if l.strip()]
    return entries[-limit:]
