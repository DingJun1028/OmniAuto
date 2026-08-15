"""Outbound webhook notifier (IDEA.md module 7 — provenance + delivery).

When Hermes Gateway webhook routing is configured (HERMES_WEBHOOK_URL +
HERMES_WEBHOOK_SECRET), AI Station pushes a `video_done` event after a job
finishes rendering. This closes the loop for the OA-Team 30 swarm:

    AI Station render done -> Hermes /webhooks/aistation-done
                          -> Telegram direct delivery (zero LLM cost)

Security: uses the Hermes **V2** signature scheme
(`X-Webhook-Signature-V2` = HMAC-SHA256 of "<timestamp>.<body>" with the
route secret, plus `X-Webhook-Timestamp`). V2 carries a timestamp so captured
requests cannot be replayed outside the ±300s window. This matches the
gateway's replay-protection guidance and supersedes the legacy body-only HMAC.

All network calls are best-effort: a notification failure must NEVER break the
render pipeline (same contract as db._log_provenance).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time

import httpx

from . import config
from .config import log

# Hermes webhook target. Set both to enable outbound completion events.
HERMES_WEBHOOK_URL = os.getenv("HERMES_WEBHOOK_URL", "")
HERMES_WEBHOOK_SECRET = os.getenv("HERMES_WEBHOOK_SECRET", config.WEBHOOK_SECRET)
_USE_HERMES = bool(HERMES_WEBHOOK_URL and HERMES_WEBHOOK_SECRET)

# Event type the Hermes `aistation-done` route accepts.
EVENT_VIDEO_DONE = "video_done"

# Hard timeout so a dead gateway can't stall the pipeline tail.
_TIMEOUT = 10.0


def _v2_signature(secret: str, timestamp: str, body: bytes) -> str:
    """HMAC-SHA256 of "<timestamp>.<body>" — Hermes webhook V2 scheme."""
    msg = f"{timestamp}.".encode() + body
    return hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()


def video_done(job_id: str, title: str, video_url: str, status: str = "done") -> bool:
    """Notify Hermes that a render finished. Returns True if delivered.

    Best-effort: any failure is logged and swallowed so the pipeline keeps
    its `done` result intact.
    """
    if not _USE_HERMES:
        log.debug("notify.video_done skipped (HERMES_WEBHOOK_URL/SECRET unset)")
        return False

    payload = {
        "event_type": EVENT_VIDEO_DONE,
        "job_id": job_id,
        "title": title,
        "status": status,
        "video_url": video_url,
    }
    body = json.dumps(payload, ensure_ascii=False).encode()
    timestamp = str(int(time.time()))
    sig = _v2_signature(HERMES_WEBHOOK_SECRET, timestamp, body)

    try:
        resp = httpx.post(
            HERMES_WEBHOOK_URL,
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Webhook-Signature-V2": sig,
                "X-Webhook-Timestamp": timestamp,
            },
            timeout=_TIMEOUT,
        )
        if resp.status_code == 200:
            log.info("notify.video_done delivered job=%s -> %s", job_id, resp.json().get("status"))
            return True
        log.warning("notify.video_done job=%s got HTTP %s", job_id, resp.status_code)
        return False
    except Exception:  # noqa: BLE001 — best-effort, never break the pipeline
        log.exception("notify.video_done job=%s failed", job_id)
        return False
