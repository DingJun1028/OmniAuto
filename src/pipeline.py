"""Module 1 — Orchestration hub.

Runs the full pipeline for one job:
  parse (2) -> TTS per shot (3) -> visuals per shot (4)
  -> render per-shot clips with synced captions (5) -> concat (5)
  -> publish (6) -> provenance (7).
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

from . import db
from . import renderer, storage, tts, visuals
from .config import STORAGE_DIR
from .parser import parse_script, Shot


def run_pipeline(job_id: str, script: str, title: str) -> str:
    work = STORAGE_DIR / job_id
    work.mkdir(parents=True, exist_ok=True)

    db.update_job(job_id, status="parsing", progress=5)
    shots = parse_script(script)
    shot_dicts = [s.to_dict() if isinstance(s, Shot) else s for s in shots]
    db.update_job(job_id, status="tts", progress=20, payload=__json(shot_dicts))

    # 3 + 4: per-shot audio (+ word timings) + frame
    frames, audios, all_boundaries = [], [], []
    total = len(shots)
    for i, s in enumerate(shots):
        sd = s.to_dict() if isinstance(s, Shot) else s
        idx = i + 1
        db.update_job(job_id, status="rendering", progress=20 + int(60 * idx / total))
        a = work / f"shot_{idx}.mp3"
        path, bounds, _silent = tts.synthesize(sd["narration"], a)
        audios.append(a)
        all_boundaries.append(bounds)
        f = work / f"shot_{idx}.png"
        visuals.render_shot_frame(sd, idx, total, f)
        frames.append(f)

    # 5: render per-shot clips (with synced captions) then concat
    db.update_job(job_id, status="rendering", progress=85)
    clips = []
    for i, (f, a) in enumerate(zip(frames, audios)):
        clip = work / f"clip_{i+1}.mp4"
        renderer.render_shot_clip(f, a, clip, i + 1, boundaries=all_boundaries[i])
        clips.append(clip)
    video = work / "final.mp4"
    renderer.render_final(clips, video, shot_dicts)

    # 6: publish
    db.update_job(job_id, status="publishing", progress=95)
    url = storage.publish(video)

    # finalize
    db.update_job(
        job_id,
        status="done",
        progress=100,
        result=__json({"video_url": url, "file": str(video), "shots": len(shots)}),
    )
    return url


def enqueue(script: str, title: str) -> dict:
    job_id = uuid.uuid4().hex[:12]
    db.create_job(job_id, title, {"script": script})
    try:
        run_pipeline(job_id, script, title)
    except Exception as e:  # keep the job record even on failure
        db.update_job(job_id, status="failed", result=__json({"error": str(e)}))
    return db.get_job(job_id)  # type: ignore[return-value]


def __json(obj) -> str:
    return json.dumps(obj, ensure_ascii=False)
