#!/usr/bin/env python3
"""Live end-to-end render check for AI Station (runs ON the VPS).

Submits a 壽司博士 DNA script to the local API, polls until the job reaches a
terminal state, and confirms the produced MP4 actually exists on disk. Uses the
free path (edge-tts + ffmpeg + Pillow) — no cloud keys required.

Run on the VPS after deploy:
    python3 verify_live.py
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request

BASE = "http://127.0.0.1:8000"


def _post(path: str, payload: dict) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        BASE + path, data=data, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def _get(path: str) -> dict:
    with urllib.request.urlopen(BASE + path, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def main() -> int:
    script = (
        "【場景】城市不是替人民設計。"
        "【衝突】市民的需求常被專家最佳化取代。"
        "【洞察】公共價值來自共創。"
        "【方法】用三個共創問題啟動參與。"
        "【反思】你上一次被詢問，是什麼時候？"
    )
    job = _post("/api/jobs", {"title": "verify-run", "script": script, "brand_preset": "sushi_dr"})
    job_id = job["job_id"]
    print(f"submitted job={job_id}")

    status = "queued"
    for i in range(60):
        time.sleep(3)
        cur = _get(f"/api/jobs/{job_id}")
        status = cur["status"]
        print(f"poll {i + 1}: {status}")
        if status in ("done", "failed"):
            break

    final = _get(f"/api/jobs/{job_id}")
    result = final.get("result") or {}
    file_path = result.get("file") if isinstance(result, dict) else None
    print("final status:", status)
    print("result:", json.dumps(result, ensure_ascii=False)[:300])

    if status != "done" or not file_path:
        print("VERIFY FAILED: job did not finish with a video")
        return 1

    import os

    if os.path.exists(file_path) and os.path.getsize(file_path) > 1000:
        print(f"VIDEO_EXISTS: {file_path} ({os.path.getsize(file_path)} bytes)")
        print("VERIFY OK")
        return 0
    print(f"VIDEO_MISSING: {file_path}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
