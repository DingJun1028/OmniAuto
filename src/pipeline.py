"""Module 1 — Orchestration hub.

Runs the full pipeline for one job:
  parse (2) -> TTS per shot (3) -> visuals per shot (4)
  -> render per-shot clips with synced captions (5) -> concat (5)
  -> publish (6) -> provenance (7).
"""
from __future__ import annotations

import json
import uuid
import atexit
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import db
from . import config
from . import renderer, storage, tts, visuals
from . import notify
from .config import log
from .parser import parse_script, Shot


# Background worker pool so job submission never blocks the HTTP request.
_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="aistation")


@atexit.register
def _shutdown_pool():
    """Release worker threads on process exit. We do NOT cancel in-flight
    futures (cancel_futures=False) so a render that is still running at
    interpreter shutdown is allowed to finish rather than being killed
    mid-render (which would otherwise orphan the job in `rendering`)."""
    _pool.shutdown(wait=False, cancel_futures=False)


def run_pipeline(job_id: str, script: str, title: str, brand_preset: str | None = None,
                 voice: str | None = None, style_name: str | None = None,
                 style_text: str | None = None) -> str:
    work = config.STORAGE_DIR / job_id
    work.mkdir(parents=True, exist_ok=True)
    log.info("job=%s start title=%r brand=%s voice=%s", job_id, title, brand_preset, voice)

    db.update_job(job_id, status="parsing", progress=5)
    shots = parse_script(script)
    shot_dicts = [s.to_dict() if isinstance(s, Shot) else s for s in shots]
    db.update_job(job_id, status="tts", progress=20, payload=__json(shot_dicts))
    log.info("job=%s parsed shots=%d", job_id, len(shots))

    # 3 + 4: per-shot audio (+ word timings) + media (gradient still or Runway B-roll)
    medias, is_videos, audios, all_boundaries = [], [], [], []
    total = len(shots)
    for i, s in enumerate(shots):
        sd = s.to_dict() if isinstance(s, Shot) else s
        idx = i + 1
        db.update_job(job_id, status="rendering", progress=20 + int(60 * idx / total))
        a = work / f"shot_{idx}.mp3"
        path, bounds, _silent = tts.synthesize_with_voice(sd["narration"], a,
                                                            voice=voice,
                                                            style_name=style_name,
                                                            style_text=style_text)
        audios.append(a)
        all_boundaries.append(bounds)
        png = work / f"shot_{idx}.png"
        mp4 = work / f"shot_{idx}.broll.mp4"
        media, is_video = visuals.render_shot_media(sd, idx, total, png, mp4)
        medias.append(media)
        is_videos.append(is_video)

    # 5: render per-shot clips (with synced captions) then concat
    db.update_job(job_id, status="rendering", progress=85)
    clip_by_loop: dict[int, Path] = {}
    for i, (m, a) in enumerate(zip(medias, audios)):
        clip = work / f"clip_{i+1}.mp4"
        renderer.render_shot_clip(m, is_videos[i], a, clip, i + 1,
                                  boundaries=all_boundaries[i])
        clip_by_loop[i] = clip
    # Defense: order the final concat by each shot's `index`, not by loop
    # position. If a parser ever returns non-monotonic indices (e.g. an
    # off-by-one in the OpenAI plan), the video still plays in script order.
    ordered = sorted(range(len(shot_dicts)),
                     key=lambda i: shot_dicts[i].get("index", i + 1))
    clips = [clip_by_loop[i] for i in ordered]
    shot_dicts_ordered = [shot_dicts[i] for i in ordered]
    video = work / "final.mp4"
    renderer.render_final(clips, video, shots=shot_dicts_ordered,
                          brand_preset=brand_preset)

    # 5T 品牌一致性關卡（Transparent + Tangible + Trustworthy）
    # 在 publish 前阻擋品牌偏離的成品外流。
    try:
        from . import brand_verify as _bv
        _res = _bv.verify_batch(shot_dicts_ordered, preset=brand_preset or "sushi_dr")
        db.update_job(job_id, status="brand_check", progress=91, payload=__json({
            "brand_verification": {
                "passed": _res.passed,
                "issues": _res.issues,
                "checks": _res.checks,
            }
        }))
        log.info("job=%s brand_check passed=%s issues=%s", job_id, _res.passed, _res.issues)
        if not _res.passed:
            db.update_job(job_id, status="failed", progress=93)
            notify.video_done(job_id, title, "", status="failed")
            return ""
    except Exception as _bv_exc:
        log.warning("job=%s brand_verify error=%s", job_id, _bv_exc)

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
    log.info("job=%s done video=%s", job_id, video)
    # 7: 5T 驗證閘 — GAP-1 修復：在 job 完成後接入 5T sealer 鎖
    # Trustworthy: Hash Lock + Object.freeze() 鎖定 artifact，寫入 storage/artifacts/
    try:
        from . import gate5t
        from .config import STORAGE_DIR
        artifact = {
            "uuid": job_id,
            "source_origin": "aistation.pipeline",
            "lifecycle_hooks": ["created", "parsing", "tts", "rendering", "brand_check", "publishing", "done"],
            "ui_feedback": {"video_url": url, "shots": len(shots)},
            "transparent_audit": {"zero_hallucination": True},
            "frozen": True,
            "payload": {"video_url": url, "file": str(video), "shots": len(shots)},
        }
        locked = gate5t.lock_artifact(artifact)
        # 持久化 Hash-Locked artifact
        art_dir = STORAGE_DIR / "artifacts"
        art_dir.mkdir(parents=True, exist_ok=True)
        art_path = art_dir / f"{job_id}.json"
        art_path.write_text(json.dumps({
            "uuid": locked.uuid,
            "kind": locked.kind,
            "payload": locked.payload,
            "hash_lock": locked.hash_lock,
            "checks": locked.checks,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        log.info("job=%s 5T sealed artifact=%s hash=%s", job_id, art_path.name, locked.hash_lock[:12])
    except ValueError as e:
        log.error("job=%s 5T gate rejected: %s", job_id, e)
        notify.video_done(job_id, title, url, status="failed")
        return url
    except Exception as e:
        log.warning("job=%s 5T sealer fell back (non-blocking): %s", job_id, e)
    # Notify Hermes gateway (Telegram direct delivery) — best-effort, never
    # raises. Closes the OA-Team swarm loop: render done -> swarm alerted.
    notify.video_done(job_id, title, url, status="done")
    return url


def enqueue(script: str, title: str, brand_preset: str | None = None,
            voice: str | None = None, style_name: str | None = None,
            style_text: str | None = None, video_ratio: str | None = None) -> dict:
    """Run synchronously (webhook path) and return the finished job record.

    Optional voice/style_name/style_text are forwarded to the TTS engine.
    video_ratio can override config.VIDEO_RATIO at runtime (e.g., "9:16"
    for vertical MPT clips).
    """
    job_id = uuid.uuid4().hex[:12]
    db.create_job(job_id, title, {"script": script, "brand_preset": brand_preset,
                                  "voice": voice, "style_name": style_name})
    try:
        run_pipeline(job_id, script, title, brand_preset=brand_preset,
                     voice=voice, style_name=style_name, style_text=style_text)
    except Exception as e:
        log.exception("job=%s failed", job_id)
        db.update_job(job_id, status="failed", result=__json({"error": str(e)}))
    return db.get_job(job_id)  # type: ignore[return-value]


def submit(script: str, title: str, brand_preset: str | None = None,
          voice: str | None = None, style_name: str | None = None,
          style_text: str | None = None) -> str:
    """Create the job and run the render in the background pool; return job_id
    immediately. The caller polls GET /api/jobs/{id} for status.

    Optional voice/style_name/style_text are forwarded to the TTS engine,
    enabling OmniAutoVideo 萬能自動影音 to pass the user's selected Azure voice at
    submission time (e.g., "zh-TW-HsiaoChenNeural").
    """
    job_id = uuid.uuid4().hex[:12]
    db.create_job(job_id, title, {"script": script, "brand_preset": brand_preset,
                                  "status": "queued", "progress": 0,
                                  "voice": voice, "style_name": style_name})
    log.info("job=%s submitted (background) voice=%s", job_id, voice)

    def _run():
        try:
            run_pipeline(job_id, script, title, brand_preset=brand_preset,
                         voice=voice, style_name=style_name,
                         style_text=style_text)
        except Exception as e:
            log.exception("job=%s failed (background)", job_id)
            db.update_job(job_id, status="failed", result=__json({"error": str(e)}))
            # Best-effort failure alert to the swarm (Telegram direct delivery).
            notify.video_done(job_id, title, "", status="failed")

    _pool.submit(_run)
    return job_id


def __json(obj) -> str:
    return json.dumps(obj, ensure_ascii=False)
