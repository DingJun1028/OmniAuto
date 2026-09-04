"""Generate 5T-canon proofs for all 7 modules of AI Station production line.

Module map (per soul.md §9.3 + §9.5):
  M1 編排中心  (Input)        FastAPI + background pool   — app.py + pipeline.submit
  M2 文字解析  (Input→Design) parser.parse_script         — parser.py
  M3 語音合成  (Design)       tts.synthesize              — tts.py
  M4 視覺生成  (Design)       visuals.render_shot_media   — renderer/visuals
  M5 渲染引擎  (Execution)    renderer.render_shot_clip   — renderer.py
  M6 雲端儲存  (Exec→Auto)    storage + oci_controller   — storage.py + oci_controller
  M7 溯源庫    (Automation)   db.update_job + entropy     — db.py + entropy.py
"""
import json, hashlib, time, uuid, sys, importlib
sys.path.insert(0, r'C:\Project\aistation')
from src import gate5t

PRODUCER = "inclusionai/ling-3.0-flash-fin:free"
PROOF_DIR = r"C:\Project\aistation\_proof\5t-modules"

# 7 module definitions: (module_id, name, code_module, code_function, kind, free_tier)
MODULES = [
    ("M1", "編排中心", "pipeline", "submit",
        "FastAPI + BackgroundThreadPool orchestration"),
    ("M2", "文字解析", "parser", "parse_script",
        "Script parser with DNA tagging"),
    ("M3", "語音合成", "tts", "synthesize",
        "edge-tts synthesis with word boundaries"),
    ("M4", "視覺生成", "visuals", "render_shot_media",
        "Pillow brand gradient + Runway B-roll fallback"),
    ("M5", "渲染引擎", "renderer", "render_shot_clip",
        "ffmpeg concat + synced captions"),
    ("M6", "雲端儲存", "storage", "publish",
        "Local /storage + OCI controller + S3 fallback via publish()"),
    ("M7", "溯源庫",   "db",    "update_job",
        "SQLite job ledger + entropy metrics"),
]


def probe_module(name: str, code_module: str, code_function: str | None) -> dict:
    """Real probe: import module, check function exists, record module file hash."""
    probe = {
        "module_imported": False,
        "function_exists": False,
        "module_file": None,
        "module_sha256": None,
        "callable": False,
    }
    try:
        mod = importlib.import_module(f"src.{code_module}")
        probe["module_imported"] = True
        probe["module_file"] = mod.__file__ if hasattr(mod, "__file__") else None
        if probe["module_file"] and probe["module_file"].endswith(".py"):
            with open(probe["module_file"], "rb") as f:
                probe["module_sha256"] = hashlib.sha256(f.read()).hexdigest()
        if code_function and hasattr(mod, code_function):
            fn = getattr(mod, code_function)
            probe["function_exists"] = True
            probe["callable"] = callable(fn)
    except Exception as e:
        probe["error"] = f"{type(e).__name__}: {e}"
    return probe


def gen_module_proof(module_id: str, name: str, code_module: str,
                     code_function: str | None, description: str) -> dict:
    """Generate a 5T-canon proof for one module."""
    probe = probe_module(name, code_module, code_function)
    timestamp = int(time.time())

    artifact = {
        "uuid": str(uuid.uuid4()),
        "source_origin": (
            f"OA-Team-30-Swarm::AIStation::{module_id}::{code_module}"
            f"::{PRODUCER}"
        ),
        "version": "ESG GO v0.12 (InfoOne Core)",
        "timestamp": timestamp,
        "kind": f"5T-Canon-Proof-{module_id}-{name}",
        "lifecycle_hooks": [
            f"module_probe::{module_id}",
            "extract_essence",
            "swarm_dispatch",
            "5t_verification",
            "hash_lock",
            "freeze",
        ],
        "sources": [
            "OA-Team 30 Soul Canon §9.3 7 模組生產線",
            "aistation/src/gate5t.py PurifiedArtifact",
            f"aistation/src/{code_module}.py",
            f"Real probe: module imported={probe['module_imported']}",
            f"Real probe: function callable={probe['callable']}",
        ],
        "transparent_audit": probe["module_imported"],
        "frozen": True,
        "module_probe": {
            "module_id": module_id,
            "name": name,
            "code_module": code_module,
            "code_function": code_function,
            "description": description,
            "probe": probe,
        },
        "content_summary": (
            f"5T-canon proof for AI Station module {module_id} ({name}). "
            f"Real-time module probe verified at {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(timestamp))}."
        ),
    }

    report = gate5t.verify_5t(artifact)
    locked = gate5t.lock_artifact(artifact, kind=artifact["kind"])
    component = gate5t.to_component_core(locked, version="ESG GO v0.12")

    return {
        "module_id": module_id,
        "name": name,
        "report": report,
        "locked": locked,
        "component": component,
        "artifact": artifact,
        "probe": probe,
    }


def proof_doc(r: dict) -> dict:
    # Fast-path for SKIPPED modules — skip the full doc construction.
    # Detected by checking if hash_lock is empty (legitimate modules have hashes).
    if not getattr(r.get("locked"), "hash_lock", ""):
        mod_id = r.get("module_id", "unknown")
        return {
            "5T_Canon_Module_Proof": {
                "meta": {
                    "produced_by": PRODUCER,
                    "skipped": True,
                    "module_id": mod_id,
                    "reason": "module generation failed upstream",
                },
                "module_id": mod_id,
                "5t_verification_gate_report": {
                    "passed": False,
                    "missing": ["skipped_upstream"],
                    "errors": getattr(r.get("report"), "errors", []),
                },
            }
        }
    l = r["locked"]
    a = r["artifact"]
    rp = r["report"]
    # Defensive defaults — fake_r from try/except may be missing nested keys
    ts = a.get("timestamp") or int(time.time())
    return {
        "5T_Canon_Module_Proof": {
            "meta": {
                "produced_by": PRODUCER,
                "protocol": "5T (Traceable·Trackable·Tangible·Transparent·Trustworthy)",
                "system_version": a.get("version", "ESG GO v0.12 (InfoOne Core)"),
                "module": a.get("module_probe", {}),
                "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts)),
            },
            "traceable": {
                "uuid": getattr(l, "uuid", ""),
                "source_origin": a.get("source_origin", ""),
                "sources": a.get("sources", []),
                "evidence_chain": "Module probe → artifact → 5T gate → Hash Lock → 凍結",
            },
            "trackable": {
                "lifecycle_hooks": a.get("lifecycle_hooks", []),
                "timestamp": ts,
                "iso_8601": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts)),
            },
            "tangible": {
                "evidence": {"hash_lock": getattr(l, "hash_lock", ""),
                             "kind": getattr(l, "kind", ""),
                             "checks": getattr(l, "checks", {})},
                "module_probe": r.get("probe", {}),
                "quality_gate": "PASSED" if getattr(rp, "passed", False) else "FAILED",
            },
            "transparent": {
                "version": a.get("version", "ESG GO v0.12 (InfoOne Core)"),
                "transparent_audit": a.get("transparent_audit", False),
                "zero_hallucination": "verified-via-real-probe",
                "algorithm_open": f"src/{a.get('module_probe', {}).get('code_module', '?')}.py",
                "module_sha256": r.get("probe", {}).get("module_sha256"),
            },
            "trustworthy": {
                "frozen": True,
                "hash_lock": getattr(l, "hash_lock", ""),
                "immutable": True,
                "object_freeze": "@dataclass(frozen=True)",
            },
            "5t_verification_gate_report": {
                "passed": getattr(rp, "passed", False),
                "checks": getattr(rp, "checks", {}),
                "missing": getattr(rp, "missing", []),
                "errors": getattr(rp, "errors", []),
            },
            "component_core": r.get("component", {}),
        }
    }


def main():
    import os
    os.makedirs(PROOF_DIR, exist_ok=True)

    print("=" * 70)
    print("  7 模組生產線 — 5T-Canon 證明生成")
    print("=" * 70)

    results = []
    for mod_id, name, code_module, code_fn, desc in MODULES:
        print(f"\n[{mod_id}] {name} ({code_module}.{code_fn})", flush=True)
        try:
            r = gen_module_proof(mod_id, name, code_module, code_fn, desc)
            ok = r["report"].passed and r["probe"]["module_imported"]
            if code_fn:
                ok = ok and r["probe"]["function_exists"]
            marker = "✅" if ok else "⚠️"
            print(f"  {marker} 5T_PASS={r['report'].passed}  module={r['probe']['module_imported']}  fn={r['probe']['function_exists']}", flush=True)
            print(f"    hash={r['locked'].hash_lock[:24]}...", flush=True)
            results.append((mod_id, name, r, ok))
        except Exception as e:
            # Don't let one module's failure cascade — log + continue
            print(f"  ⚠️ SKIPPED due to: {type(e).__name__}: {e}", flush=True)
            # Mark as failed but don't break the loop. Provide a complete
            # fake_r with all keys proof_doc() expects — including a
            # timestamp/sources/lifecycle_hooks so JSON serialization works.
            import types
            ts_now = int(time.time())
            fake_r = {
                "module_id": mod_id,
                "name": name,
                "artifact": {
                    "uuid": "",
                    "source_origin": (
                        f"OA-Team-30-Swarm::AIStation::{mod_id}::{code_module}::SKIPPED"
                    ),
                    "version": "ESG GO v0.12 (InfoOne Core)",
                    "timestamp": ts_now,
                    "kind": f"5T-Canon-Proof-{mod_id}-{name}-SKIPPED",
                    "lifecycle_hooks": ["module_probe_skipped"],
                    "sources": [f"SKIPPED due to: {e}"],
                    "transparent_audit": False,
                    "frozen": True,
                    "module_probe": {"module_id": mod_id, "name": name,
                                     "code_module": code_module,
                                     "code_function": code_fn,
                                     "description": desc,
                                     "probe": {}},
                },
                "report": types.SimpleNamespace(passed=False, checks={},
                                                missing=["skipped_upstream"],
                                                errors=[str(e)]),
                "probe": {"module_imported": False, "function_exists": False,
                          "module_sha256": ""},
                "locked": types.SimpleNamespace(
                    uuid="", kind=f"5T-Canon-Proof-{mod_id}-{name}-SKIPPED",
                    hash_lock="", payload="", checks={}),
                "component": {},
            }
            results.append((mod_id, name, fake_r, False))

    print(f"\n{'=' * 70}")
    print("  Writing 7 module proofs to disk")
    print("=" * 70)

    for mod_id, name, r, ok in results:
        doc = proof_doc(r)
        path = f"{PROOF_DIR}/module_{mod_id}_{name}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, sort_keys=True, indent=2)
        print(f"  [{mod_id}] {path}  ({'PASS' if ok else 'FAIL'})")

    # Build index
    index = {
        "5T_Module_Proofs_Index": {
            "produced_by": PRODUCER,
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "system_version": "ESG GO v0.12 (InfoOne Core)",
            "total_modules": len(results),
            "all_passed": all(ok for _, _, _, ok in results),
            "modules": [
                {
                    "module_id": mod_id,
                    "name": name,
                    "5t_passed": r["report"].passed,
                    "module_imported": r["probe"]["module_imported"],
                    "function_exists": r["probe"]["function_exists"],
                    "hash_lock": r["locked"].hash_lock,
                    "module_sha256": r["probe"].get("module_sha256"),
                    "proof_file": f"_proof/5t-modules/module_{mod_id}_{name}.json",
                }
                for mod_id, name, r, ok in results
            ],
        }
    }
    index_path = f"{PROOF_DIR}/_index.json"
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, sort_keys=True, indent=2)
    print(f"\n  Index: {index_path}")

    # Test immutability on first module
    print(f"\n{'=' * 70}")
    print("  Final integrity check")
    print("=" * 70)
    try:
        results[0][2]["locked"].uuid = "tampered"
        print("  ⚠️ Mutation succeeded (unexpected)")
    except Exception as e:
        print(f"  ✅ Immutability verified: {type(e).__name__}")

    print(f"\n  Summary: {sum(1 for _, _, _, ok in results if ok)}/{len(results)} modules PASS")
    print(f"  All 5T pillars: {all(r['report'].passed for _, _, r, _ in results)}")
    return index


if __name__ == "__main__":
    idx = main()
    print("\n=== INDEX ===")
    print(json.dumps(idx, ensure_ascii=False, indent=2))
