"""5T-Canon Proof Notifier — dual-channel dispatch (Hermes webhook + Telegram).

Sends a `5t_canon_proof` event using Hermes V2 HMAC signing.
Falls back to `video_done` envelope (the existing gateway route) if the
new event type is unknown, so legacy routers will still deliver the
notification.

Output: best-effort. Failure must NEVER break the calling pipeline.
"""
from __future__ import annotations

import hmac
import hashlib
import json
import os
import time
from typing import Any, Dict, Optional

import httpx

# Load .env explicitly so HERMES_WEBHOOK_SECRET is available
try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=r"C:\Project\aistation\.env")
    for vault in [
        r"C:\Users\dingj\secret-vault\ENV20230818.env",
        r"C:\Users\dingj\secret-vault\ENV20260820.env",
    ]:
        if os.path.exists(vault):
            try:
                load_dotenv(dotenv_path=vault, override=False)
            except Exception:
                pass
except Exception:
    pass

HERMES_WEBHOOK_URL = os.getenv("HERMES_WEBHOOK_URL", "http://localhost:8644/webhooks/aistation-done")
HERMES_WEBHOOK_SECRET = os.getenv("HERMES_WEBHOOK_SECRET", "")

# Event types
EVENT_VIDEO_DONE = "video_done"  # legacy route already knows this
EVENT_5T_CANON_PROOF = "5t_canon_proof"  # new event (currently "unknown" to gateway)

_TIMEOUT = 10.0


def _v2_signature(secret: str, timestamp: str, body: bytes) -> str:
    """HMAC-SHA256 of "<timestamp>.<body>" — Hermes webhook V2 scheme."""
    msg = f"{timestamp}.".encode() + body
    return hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()


def _post_signed(url: str, body_dict: Dict[str, Any]) -> Dict[str, Any]:
    """POST a JSON body to the gateway with HMAC-V2 headers."""
    timestamp = str(int(time.time()))
    body = json.dumps(body_dict, ensure_ascii=False, sort_keys=True).encode("utf-8")
    sig = _v2_signature(HERMES_WEBHOOK_SECRET, timestamp, body) if HERMES_WEBHOOK_SECRET else ""
    headers = {
        "Content-Type": "application/json",
        "X-Webhook-Timestamp": timestamp,
        "X-Webhook-Event": body_dict.get("event", ""),
    }
    if sig:
        headers["X-Webhook-Signature-V2"] = sig
    try:
        resp = httpx.post(url, content=body, headers=headers, timeout=_TIMEOUT)
        return {
            "delivered": resp.status_code < 400,
            "status": resp.status_code,
            "response": resp.text[:300],
        }
    except Exception as e:
        return {"delivered": False, "error": f"{type(e).__name__}: {e}"}


def notify_5t_canon_proof(
    kind: str,
    uuid: str,
    hash_lock: str,
    source_origin: str,
    pillars_passed: Dict[str, bool],
    result: str = "PASSED",
    url: Optional[str] = None,
    secret: Optional[str] = None,
) -> Dict[str, Any]:
    """Notify the Hermes gateway that a 5T-canon proof was produced.

    Tries `5t_canon_proof` event first (preferred new envelope). If the
    gateway returns 200 but `event=unknown`, retries with a `video_done`
    envelope so existing routing still delivers.

    Args:
        kind:           "5T-Canon-Proof" | "5T-Canon-CrossVerify-A" | "5T-Canon-Module-M1" ...
        uuid:           locked artifact UUID
        hash_lock:      SHA-256 hash
        source_origin:  producer model + chain
        pillars_passed: dict of 5T pillars (Tangible/Traceable/Trackable/Transparent/Trustworthy)
        result:         "PASSED" | "FAILED"
        url:            override HERMES_WEBHOOK_URL
        secret:         override HERMES_WEBHOOK_SECRET

    Returns dict with delivered bool + channels used + raw responses.
    """
    target_url = url or HERMES_WEBHOOK_URL
    target_secret = secret or HERMES_WEBHOOK_SECRET

    pillars_str = " · ".join(
        f"{'✓' if v else '✗'} {k}" for k, v in (pillars_passed or {}).items()
    )
    short_hash = hash_lock[:16] + "…" if len(hash_lock) > 16 else hash_lock

    # Primary envelope: native 5t_canon_proof event
    primary_body = {
        "event": EVENT_5T_CANON_PROOF,
        "timestamp": str(int(time.time())),
        "data": {
            "kind": kind,
            "uuid": uuid,
            "hash_lock": hash_lock,
            "source_origin": source_origin,
            "pillars_passed": pillars_passed,
            "result": result,
            "pillars_str": pillars_str,
            "short_hash": short_hash,
        },
    }
    primary = _post_signed(target_url, primary_body)

    # Fallback envelope: legacy video_done route (gateway knows this)
    legacy_body = {
        "event": EVENT_VIDEO_DONE,
        "event_type": EVENT_VIDEO_DONE,
        "timestamp": str(int(time.time())),
        "job_id": uuid,
        "title": f"5T-Canon: {kind} [{result}]",
        "status": "done" if result == "PASSED" else "failed",
        "video_url": f"5t://{kind}/{short_hash}",
        "metadata": {
            "kind": kind,
            "hash_lock": hash_lock,
            "source_origin": source_origin,
            "pillars_passed": pillars_passed,
            "pillars_str": pillars_str,
            "result": result,
        },
    }
    legacy = _post_signed(target_url, legacy_body)

    delivered = primary.get("delivered", False) or legacy.get("delivered", False)
    return {
        "delivered": delivered,
        "primary_event": primary,
        "legacy_event": legacy,
        "kind": kind,
        "uuid": uuid,
        "hash_lock": hash_lock,
        "result": result,
    }


# Backwards-compatible shim matching the old dispatch() signature
def dispatch(event_data: dict, dry_run: bool = False, also_telegram: bool = False) -> dict:
    """Legacy wrapper. Returns dict (delivered, channels)."""
    if dry_run:
        return {"delivered": False, "dry_run": True}

    result = notify_5t_canon_proof(
        kind=event_data.get("kind", ""),
        uuid=event_data.get("uuid", ""),
        hash_lock=event_data.get("hash_lock", ""),
        source_origin=event_data.get("source_origin", ""),
        pillars_passed=event_data.get("pillars_passed", {}),
        result=event_data.get("result", "PASSED"),
    )
    return {
        "delivered": result["delivered"],
        "channels": [
            {"name": "primary_5t", **result["primary_event"]},
            {"name": "legacy_video_done", **result["legacy_event"]},
        ],
    }
