"""Pitfall test: cron env without PYTHONIOENCODING crashes gen_5t_7modules.py.

This reproduces the cp950 UnicodeEncodeError that caused M1/M4/M5 to fail
in Hermes cron envs where stdout defaulted to Big5 and crashed on ✅ emoji.

Fix: gen_5t_7modules.py now reconfigure()s stdout to utf-8 in its preamble.
"""
import os
import subprocess
import sys
from pathlib import Path


def test_gen_5t_7modules_works_in_cron_env():
    """Simulate Hermes cron fully-stripped env (no PYTHONIOENCODING, no HOME).

    With the UTF-8 reconfigure fix, M1-M7 must all pass.
    """
    repo = Path(r"C:\Project\aistation")
    python_exe = repo / ".venv" / "Scripts" / "python.exe"

    # Strict clean env: only PATH/SYSTEMROOT/TEMP
    clean_env = {
        k: v for k, v in os.environ.items()
        if k.upper() in ("PATH", "SYSTEMROOT", "TEMP", "TMP", "PATHEXT")
    }
    # Explicitly NOT setting PYTHONIOENCODING, HOME, USERPROFILE
    assert "PYTHONIOENCODING" not in clean_env

    proc = subprocess.run(
        [str(python_exe), str(repo / "gen_5t_7modules.py")],
        env=clean_env, cwd=str(repo),
        capture_output=True, text=True, timeout=60,
    )

    # rc may be 0 or 1 depending on whether all modules passed
    # but must NOT crash with UnicodeEncodeError
    combined = proc.stdout + proc.stderr
    assert "UnicodeEncodeError" not in combined, (
        f"gen_5t_7modules.py crashed with UnicodeEncodeError:\n{combined[-1500:]}"
    )
    assert "UnicodeDecodeError" not in combined

    # Verify _index.json was updated and all_passed
    index_path = repo / "_proof" / "5t-modules" / "_index.json"
    assert index_path.exists(), "index file missing"
    import json
    idx = json.loads(index_path.read_text(encoding="utf-8"))
    inner = idx.get("5T_Module_Proofs_Index", idx)
    modules = inner.get("modules", [])
    assert len(modules) == 7, f"expected 7 modules, got {len(modules)}"
    failed = [m["module_id"] for m in modules if not m.get("5t_passed")]
    assert not failed, f"failed modules in clean cron env: {failed}"


if __name__ == "__main__":
    test_gen_5t_7modules_works_in_cron_env()
    print("✅ cp950 pitfall test passed — gen_5t_7modules.py works in stripped cron env")
