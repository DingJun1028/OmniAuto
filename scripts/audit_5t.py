"""Automated 5T audit sweep (§24 Gap Diagnosis — 5T 稽核零缺漏).

Scans the on-disk artifact store and verifies every frozen artifact
through the 5T gate + Hash Lock tamper detection. Designed to run as a
standalone CLI or via cron.

Usage:
    python scripts/audit_5t.py                    # sweep + report
    python scripts/audit_5t.py --fix             # report + attempt removal of tampered
    python scripts/audit_5t.py --json            # machine-readable output

Free-local by default — reads JSON artifacts from STORAGE_DIR/artifacts/.
Reports real numbers, never fabricates.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import gate5t, config  # noqa: E402

log = config.log


def _discover_artifacts(artifacts_dir: Path) -> List[Path]:
    """Find all .json files in the artifacts directory."""
    if not artifacts_dir.exists():
        return []
    return sorted(f for f in artifacts_dir.iterdir() if f.suffix == ".json")


def _load_artifact(path: Path) -> Dict[str, Any] | None:
    """Load a JSON artifact file, return None on parse error."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        log.warning("audit_5t: cannot parse %s: %s", path.name, e)
        return None


def audit_artifacts(artifacts_dir: Path | None = None) -> Dict[str, Any]:
    """Run a full 5T audit sweep over all frozen artifacts.

    Returns:
        {
            "total": int,          # total artifacts found
            "verified": int,       # passed Hash Lock verification
            "tampered": int,       # hash mismatch (tampered or corrupted)
            "failed": int,         # failed 5T gate re-verification
            "pass_rate": float,    # verified / total (or 1.0 if empty)
            "details": [...],      # per-artifact results
            "timestamp": str,      # ISO 8601 UTC
        }
    """
    art_dir = artifacts_dir or (config.STORAGE_DIR / "artifacts")
    files = _discover_artifacts(art_dir)
    total = len(files)

    verified = 0
    tampered = 0
    failed = 0
    details: List[Dict[str, Any]] = []

    for f in files:
        data = _load_artifact(f)
        if data is None:
            failed += 1
            details.append({
                "file": f.name,
                "status": "parse_error",
                "uuid": None,
            })
            continue

        uuid = data.get("uuid", "")
        hash_lock = data.get("hash_lock", "")
        checks = data.get("checks", {})
        payload = data.get("payload", "")

        # Reconstruct LockedArtifact for tamper detection
        try:
            locked = gate5t.LockedArtifact(
                uuid=uuid,
                kind=data.get("kind", "artifact"),
                payload=payload,
                hash_lock=hash_lock,
                checks=checks,
            )
            hash_ok = gate5t.verify_locked(locked)
        except Exception:
            hash_ok = False

        # Re-run 5T gate on the payload
        try:
            _payload = json.loads(payload) if isinstance(payload, str) else payload
            gate_report = gate5t.verify_5t(_payload)
            gate_pass = gate_report.passed
        except Exception:
            gate_pass = False

        if not hash_ok:
            tampered += 1
            status = "tampered"
        elif not gate_pass:
            failed += 1
            status = "5t_failed"
        else:
            verified += 1
            status = "verified"

        details.append({
            "file": f.name,
            "uuid": uuid,
            "status": status,
            "hash_lock_ok": hash_ok,
            "5t_passed": gate_pass,
            "checks": checks,
        })

    pass_rate = round(verified / total, 4) if total else 1.0

    return {
        "total": total,
        "verified": verified,
        "tampered": tampered,
        "failed": failed,
        "pass_rate": pass_rate,
        "details": details,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="5T audit sweep (§24)")
    ap.add_argument("--fix", action="store_true",
                    help="remove tampered/failed artifacts after reporting")
    ap.add_argument("--json", action="store_true",
                    help="output machine-readable JSON")
    ap.add_argument("--with-entropy", action="store_true",
                    help="also compute current system entropy and merge into output")
    args = ap.parse_args()

    result = audit_artifacts()

    if args.with_entropy:
        try:
            from src import entropy
            ent = entropy.compute_entropy()
            result["entropy"] = ent["entropy"]
            result["entropy_status"] = ent["status"]
            result["entropy_components"] = ent["components"]
        except Exception as e:
            log.warning("audit_5t: entropy computation failed: %s", e)

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        ts = result["timestamp"]
        print(f"## 5T 稽核報告 — {ts}")
        print(f"  總件數: {result['total']}")
        print(f"  驗證通過: {result['verified']}")
        print(f"  篡改檢測: {result['tampered']}")
        print(f"  5T 閘失敗: {result['failed']}")
        print(f"  通過率: {result['pass_rate'] * 100:.1f}%")
        print()
        if result["details"]:
            for d in result["details"]:
                marker = "  "
                if d["status"] == "tampered":
                    marker = "  TAMPERED! "
                elif d["status"] == "5t_failed":
                    marker = "  5T FAILED "
                elif d["status"] == "parse_error":
                    marker = "  PARSE ERROR "
                print(f"  {marker} {d['file']} (uuid={d.get('uuid', 'N/A')})")

    if args.fix:
        art_dir = config.STORAGE_DIR / "artifacts"
        removed = 0
        for d in result["details"]:
            if d["status"] in ("tampered", "5t_failed", "parse_error"):
                fpath = art_dir / d["file"]
                if fpath.exists():
                    fpath.unlink()
                    removed += 1
                    log.warning("audit_5t: removed %s (status=%s)", d["file"], d["status"])
        print(f"\n  已移除 {removed} 件不合格 artifact（--fix）")

    # Exit non-zero if any failures
    return 1 if (result["tampered"] > 0 or result["failed"] > 0) else 0


if __name__ == "__main__":
    raise SystemExit(main())
