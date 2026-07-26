"""Live end-to-end smoke test for AI Station.

Renders a REAL video using the actual free stack (edge-tts + ffmpeg + Pillow),
isolated to a temp dir (no pollution of repo storage/ or jobs.db).
Verifies the output is a valid, non-empty MP4.

Run:  python scripts/live_smoke.py
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# Ensure project root on path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import src.config as config
import src.db as db
from src import pipeline

SCRIPT = """【場景】城市不是替人民設計。
【衝突】市民的需求常被專家最佳化取代。
【洞察】公共價值來自共創。
【方法】用三個共創問題啟動參與。
【反思】你上一次被詢問，是什麼時候？"""

TITLE = "live-smoke-壽司博士"


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="aistation-smoke-"))
    config.STORAGE_DIR = tmp
    db.DB_PATH = tmp / "jobs.db"
    db.init_db()  # create the jobs table in the isolated db
    config.setup_logging()
    print(f"[smoke] temp workspace: {tmp}")
    print(f"[smoke] font resolved: {config.FONT_PATH}")
    print(f"[smoke] features: {json.dumps(config.feature_summary(), ensure_ascii=False)}")

    job_id = pipeline.submit(TITLE, TITLE, brand_preset="sushi_dr")
    print(f"[smoke] submitted job_id={job_id}")

    # poll until terminal status
    import time
    for _ in range(120):
        rec = db.get_job(job_id)
        st = rec["status"]
        if st in ("done", "failed"):
            break
        time.sleep(1)
    else:
        print("[smoke] TIMEOUT: job never reached terminal state", file=sys.stderr)
        return 2

    rec = db.get_job(job_id)
    print(f"[smoke] final status={rec['status']} progress={rec['progress']}")
    if rec["status"] != "done":
        print(f"[smoke] FAILED: {rec.get('result')}", file=sys.stderr)
        return 1

    result = json.loads(rec["result"])
    video = Path(result["file"])
    print(f"[smoke] video_url={result['video_url']} shots={result['shots']}")
    if not video.exists() or video.stat().st_size == 0:
        print(f"[smoke] FAILED: output missing/empty: {video}", file=sys.stderr)
        return 1

    # validate it's a real playable mp4
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "format=duration,format_name:stream=codec_type,codec_name",
         "-of", "json", str(video)],
        capture_output=True, text=True,
    )
    if probe.returncode != 0:
        print(f"[smoke] FAILED: ffprobe error: {probe.stderr}", file=sys.stderr)
        return 1
    info = json.loads(probe.stdout)
    dur = float(info["format"]["duration"])
    streams = {s["codec_type"]: s["codec_name"] for s in info["streams"]}
    print(f"[smoke] ffprobe: duration={dur:.2f}s format={info['format']['format_name']} streams={streams}")
    if dur <= 0 or "video" not in streams:
        print("[smoke] FAILED: invalid media", file=sys.stderr)
        return 1

    print(f"[smoke] OK — real video rendered: {video} ({video.stat().st_size} bytes)")
    # cleanup
    shutil.rmtree(tmp, ignore_errors=True)
    print("[smoke] cleaned up temp workspace")
    return 0


if __name__ == "__main__":
    sys.exit(main())
