"""Module 1 — Orchestration hub.

Runs the full pipeline for one job:
  parse (2) -> TTS per shot (3) -> visuals per shot (4)
  -> render per-shot clips with synced captions (5) -> concat (5)
  -> publish (6) -> provenance (7).
"""
from __future__ import annotations

import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import db
from . import renderer, storage, tts, visuals
from .config import STORAGE_DIR
from .parser import parse_script, Shot


# Background worker pool so job submission never blocks the HTTP request.
_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="aistation")


def run_pipeline(job_id: str, script: str, title: str, brand_preset: str | None = None) -> str:
    work = STORAGE_DIR / job_id
    work.mkdir(parents=True, exist_ok=True)

    db.update_job(job_id, status="parsing", progress=5)
    shots = parse_script(script)
    shot_dicts = [s.to_dict() if isinstance(s, Shot) else s for s in shots]
    db.update_job(job_id, status="tts", progress=20, payload=__json(shot_dicts))

    # 3 + 4: per-shot audio (+ word timings) + media (gradient still or Runway B-roll)
    medias, is_videos, audios, all_boundaries = [], [], [], []
    total = len(shots)
    for i, s in enumerate(shots):
        sd = s.to_dict() if isinstance(s, Shot) else s
        idx = i + 1
        db.update_job(job_id, status="rendering", progress=20 + int(60 * idx / total))
        a = work / f"shot_{idx}.mp3"
        path, bounds, _silent = tts.synthesize(sd["narration"], a)
        audios.append(a)
        all_boundaries.append(bounds)
        png = work / f"shot_{idx}.png"
        mp4 = work / f"shot_{idx}.broll.mp4"
        media, is_video = visuals.render_shot_media(sd, idx, total, png, mp4)
        medias.append(media)
        is_videos.append(is_video)

    # 5: render per-shot clips (with synced captions) then concat
    db.update_job(job_id, status="rendering", progress=85)
    clips = []
    for i, (m, a) in enumerate(zip(medias, audios)):
        clip = work / f"clip_{i+1}.mp4"
        renderer.render_shot_clip(m, is_videos[i], a, clip, i + 1,
                                  boundaries=all_boundaries[i])
        clips.append(clip)
    video = work / "final.mp4"
    renderer.render_final(clips, video, shot_dicts, brand_preset=brand_preset)

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


def enqueue(script: str, title: str, brand_preset: str | None = None) -> dict:
    """Run synchronously (webhook path) and return the finished job record."""
    job_id = uuid.uuid4().hex[:12]
    db.create_job(job_id, title, {"script": script, "brand_preset": brand_preset})
    try:
        run_pipeline(job_id, script, title, brand_preset=brand_preset)
    except Exception as e:  # keep the job record even on failure
        db.update_job(job_id, status="failed", result=__json({"error": str(e)}))
    return db.get_job(job_id)  # type: ignore[return-value]


def submit(script: str, title: str, brand_preset: str | None = None) -> str:
    """Create the job and run the render in the background pool; return job_id
    immediately. The caller polls GET /api/jobs/{id} for status."""
    job_id = uuid.uuid4().hex[:12]
    db.create_job(job_id, title, {"script": script, "brand_preset": brand_preset,
                                  "status": "queued", "progress": 0})
    _pool.submit(run_pipeline, job_id, script, title, brand_preset)
    return job_id


def __json(obj) -> str:
    return json.dumps(obj, ensure_ascii=False)
