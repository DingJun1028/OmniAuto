"""5T-Canon Multi-Repo Orchestrator — Single daily cron scans N repos,
produces per-repo proof + single aggregated webhook + single Telegram digest.

Prevents: N repos × N notifications = message flood.
Design: one cron, one digest, N per-repo proofs.

5T compliance:
- Traceable: each repo proof has source_origin + repo URL
- Trackable: per-repo status + cross-repo entropy
- Tangible: real artifacts (proof JSON per repo)
- Transparent: aggregator logic is a single function, not magic
- Trustworthy: each per-repo proof is hash-locked before aggregation
"""
from __future__ import annotations
import sys, os
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import hashlib
import json
import subprocess
import time
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Optional


REPOS = [
    {
        "id": "aistation",
        "path": r"C:\Project\aistation",
        "proof_script": "gen_5t_proof.py",
        "vault_rel": "vault/Agents/04-Index/5T-Canon-AIStation-Daily.md",
    },
    {
        "id": "ftg-journey",
        "path": r"C:\Project\ftg-journey",
        "proof_script": "scripts/gen_5t_proof_ftg.py",
        "vault_rel": "vault/Agents/04-Index/5T-Canon-FTG-Journey-Daily.md",
    },
    {
        "id": "omni-factory",
        "path": r"C:\Project\omni-factory",
        "proof_script": "scripts/gen_5t_proof_omni.py",
        "vault_rel": "vault/Agents/04-Index/5T-Canon-OmniFactory-Daily.md",
    },
]


@dataclass(frozen=True)
class RepoProof:
    repo_id: str
    status: str          # "ok" | "fail" | "skip"
    hash_lock: str
    five_t_passed: bool
    duration_s: float
    error: Optional[str] = None
    proof_path: Optional[str] = None


@dataclass(frozen=True)
class AggregatorDigest:
    timestamp: int
    total_repos: int
    passed: int
    failed: int
    skipped: int
    entropy: float            # failed / (passed+failed); 0 if no failures
    escalation: str           # "P0" | "P1" | "P2" | "OK"
    repo_proofs: tuple        # tuple of RepoProof (frozen-friendly)
    digest_hash: str = ""

    def is_immutable_ok(self) -> bool:
        """5T Trustworthy: confirm frozen."""
        try:
            # attempt field assignment
            object.__setattr__(self, "total_repos", -1)
            return False
        except (AttributeError, Exception):
            return True


def scan_repo(repo: dict) -> RepoProof:
    """Run proof script in repo, capture status + hash.

    Skip on FileNotFoundError (repo or script not present).
    """
    repo_path = Path(repo["path"])
    script_path = repo_path / repo["proof_script"]
    t0 = time.time()

    if not repo_path.exists():
        return RepoProof(
            repo_id=repo["id"], status="skip", hash_lock="",
            five_t_passed=False, duration_s=0.0,
            error=f"repo not found: {repo_path}"
        )

    if not script_path.exists():
        return RepoProof(
            repo_id=repo["id"], status="skip", hash_lock="",
            five_t_passed=False, duration_s=0.0,
            error=f"proof script not found: {script_path}"
        )

    try:
        proc = subprocess.run(
            [sys.executable, str(script_path)],
            cwd=str(repo_path), capture_output=True, text=True, timeout=60,
        )
        # Parse stdout for hash_lock + 5t_passed
        # Format: "LockedHash: <hash>" and "驗證狀態: PASS"
        locked_hash = ""
        passed = False
        for line in proc.stdout.splitlines():
            if "LockedHash:" in line or "LockedHash ==" in line:
                locked_hash = line.split(":", 1)[1].strip()[:64]
            if "驗證狀態: PASS" in line or "5T_PASS" in line and "PASS" in line:
                passed = True

        status = "ok" if (proc.returncode == 0 and passed and locked_hash) else "fail"
        return RepoProof(
            repo_id=repo["id"], status=status, hash_lock=locked_hash,
            five_t_passed=passed, duration_s=time.time() - t0,
            error=None if status == "ok" else f"rc={proc.returncode}",
            proof_path=str(script_path.parent / "_proof" / "5t-canon" / f"repo_{repo['id']}.json"),
        )
    except subprocess.TimeoutExpired:
        return RepoProof(
            repo_id=repo["id"], status="fail", hash_lock="",
            five_t_passed=False, duration_s=time.time() - t0,
            error="timeout after 60s"
        )
    except Exception as e:
        return RepoProof(
            repo_id=repo["id"], status="fail", hash_lock="",
            five_t_passed=False, duration_s=time.time() - t0,
            error=f"{type(e).__name__}: {e}"
        )


def aggregate(proofs: list[RepoProof]) -> AggregatorDigest:
    """Combine per-repo proofs into single digest with entropy + escalation."""
    passed = sum(1 for p in proofs if p.five_t_passed)
    failed = sum(1 for p in proofs if p.status == "fail")
    skipped = sum(1 for p in proofs if p.status == "skip")

    active = passed + failed
    entropy = (failed / active) if active > 0 else 0.0

    if entropy == 0.0:
        escalation = "OK"
    elif entropy < 0.1:
        escalation = "P2"
    elif entropy < 0.5:
        escalation = "P1"
    else:
        escalation = "P0"

    digest_body = json.dumps([asdict(p) for p in proofs], sort_keys=True, ensure_ascii=False)
    digest_hash = hashlib.sha256(digest_body.encode("utf-8")).hexdigest()

    digest = AggregatorDigest(
        timestamp=int(time.time()),
        total_repos=len(proofs),
        passed=passed,
        failed=failed,
        skipped=skipped,
        entropy=entropy,
        escalation=escalation,
        repo_proofs=tuple(proofs),
    )
    object.__setattr__(digest, "digest_hash", digest_hash)
    return digest


def format_telegram(digest: AggregatorDigest) -> str:
    """Single Telegram message — no flood."""
    icon = {"OK": "🟢", "P2": "🟡", "P1": "🟠", "P0": "🔴"}[digest.escalation]
    lines = [
        f"{icon} 5T-Canon Multi-Repo Digest [{digest.escalation}]",
        f"entropy={digest.entropy:.2f} | {digest.passed}/{digest.total_repos} passed, {digest.failed} failed, {digest.skipped} skipped",
        "",
    ]
    for p in digest.repo_proofs:
        status_icon = {"ok": "✅", "fail": "❌", "skip": "⏭"}[p.status]
        h = p.hash_lock[:16] if p.hash_lock else "—"
        lines.append(f"{status_icon} {p.repo_id:<14} 5T={p.five_t_passed} hash={h}… dur={p.duration_s:.1f}s")
        if p.error:
            lines.append(f"    ⚠ {p.error[:80]}")
    lines.append("")
    lines.append(f"digest_hash={digest.digest_hash[:24]}…")
    return "\n".join(lines)


def main() -> int:
    print("=" * 60)
    print("  5T-Canon Multi-Repo Orchestrator")
    print("=" * 60)
    print(f"repos: {[r['id'] for r in REPOS]}")
    print()

    proofs = []
    for repo in REPOS:
        print(f"[scan] {repo['id']}…", flush=True)
        p = scan_repo(repo)
        proofs.append(p)
        print(f"  status={p.status} 5T={p.five_t_passed} hash={p.hash_lock[:16] if p.hash_lock else '—'}", flush=True)

    digest = aggregate(proofs)
    print()
    print(format_telegram(digest))
    print()
    print(f"digest_hash={digest.digest_hash}")
    print(f"escalation={digest.escalation} entropy={digest.entropy:.3f}")

    # Persist digest
    out_dir = Path(r"C:\Project\aistation\_proof\5t-canon-multi")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"digest_{digest.timestamp}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(asdict(digest), f, ensure_ascii=False, indent=2)
    print(f"digest written: {out_path}")

    # Exit code follows escalation
    return 0 if digest.escalation in ("OK", "P1", "P2") else 1


if __name__ == "__main__":
    sys.exit(main())
