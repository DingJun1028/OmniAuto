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
    raw_result = final.get("result")
    # The API stores `result` as a JSON string, not a parsed object.
    if isinstance(raw_result, str):
        try:
            result = json.loads(raw_result)
        except Exception:
            result = {}
    else:
        result = raw_result or {}
    video_url = result.get("video_url") if isinstance(result, dict) else None
    print("final status:", status)
    print("result:", json.dumps(result, ensure_ascii=False)[:300])

    if status != "done" or not video_url:
        print("VERIFY FAILED: job did not finish with a video")
        return 1

    # Verify end-to-end via the served URL (path-independent; works regardless
    # of how storage is mounted on the host vs inside the container).
    url = BASE + video_url
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            data = r.read()
        if r.status == 200 and len(data) > 1000:
            print(f"VIDEO_SERVED_OK: {url} ({len(data)} bytes)")
            print("VERIFY OK")
            return 0
        print(f"VIDEO_SERVE_FAILED: status={r.status} bytes={len(data)}")
        return 1
    except Exception as e:
        print(f"VIDEO_SERVE_ERROR: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
