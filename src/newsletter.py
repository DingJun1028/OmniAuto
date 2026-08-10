"""電子報發送 (Chapter 10 best-practice newsletter integration).

Sends 5T-frozen artifacts / KPI snapshots to subscribers via free, self-hosted
channels: SMTP (email), Telegram Bot API (message_thread_id), Slack webhook,
and n8n HTTP trigger. No paid SaaS required — every channel uses free/local
tooling or a self-hosted endpoint.

Security (5T Trustworthy):
  - Outbound webhooks are HMAC-signed (V2 scheme, replay-protected).
  - Template values are frozen (Object.freeze equivalent) before render.
  - Rate limits per channel prevent accidental flood.
  - One-click unsubscribe + reason capture (Transparent).

Best-effort: a delivery failure must NEVER break the upstream pipeline.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import smtplib
import time
from dataclasses import dataclass, field
from email.message import EmailMessage
from typing import Dict, List, Optional

import httpx

from . import config
from .config import log

# Per-channel rate ceilings (§十 10.9 安全防護).
_RATE_LIMITS = {
    "email": 100,       # per minute
    "telegram": 30,     # per second
    "slack": 1,         # per second
    "n8n": 60,          # per minute
}

# Newsletter types from §十 10.9.
NEWSLETTER_TYPES = [
    "weekly_swarm", "ai_station_update", "5t_compliance",
    "member_spotlight", "entropy_report", "security_audit",
]


@dataclass(frozen=True)
class NewsletterTemplate:
    """Frozen template values (Trustworthy: immutable once built)."""
    newsletter_type: str
    subject: str
    body: str


@dataclass
class DispatchResult:
    channel: str
    delivered: bool
    detail: str = ""


class _RateLimiter:
    """Simple in-process token bucket keyed by channel."""

    def __init__(self) -> None:
        self._hits: Dict[str, List[float]] = {}

    def allow(self, channel: str) -> bool:
        ceiling = _RATE_LIMITS.get(channel, 10)
        now = time.time()
        window = self._hits.setdefault(channel, [])
        # keep only the last 60s of timestamps
        self._hits[channel] = [t for t in window if now - t < 60.0]
        if len(self._hits[channel]) >= ceiling:
            return False
        self._hits[channel].append(now)
        return True


_RATE = _RateLimiter()


def build_template(newsletter_type: str, subject: str, body: str) -> NewsletterTemplate:
    if newsletter_type not in NEWSLETTER_TYPES:
        raise ValueError(f"unknown newsletter_type: {newsletter_type}")
    return NewsletterTemplate(newsletter_type=newsletter_type, subject=subject, body=body)


def _v2_signature(secret: str, timestamp: str, body: bytes) -> str:
    msg = f"{timestamp}.".encode() + body
    return hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()


def _send_email(tmpl: NewsletterTemplate, to: str) -> DispatchResult:
    host = os.getenv("SMTP_HOST", "")
    if not host:
        return DispatchResult("email", False, "SMTP_HOST unset")
    if not _RATE._allow("email"):
        return DispatchResult("email", False, "rate limited")
    msg = EmailMessage()
    msg["Subject"] = tmpl.subject
    msg["To"] = to
    msg.set_content(tmpl.body)
    try:
        with smtplib.SMTP(host, int(os.getenv("SMTP_PORT", "25"))) as s:
            if os.getenv("SMTP_USER"):
                s.starttls()
                s.login(os.getenv("SMTP_USER", ""), os.getenv("SMTP_PASS", ""))
            s.send_message(msg)
        return DispatchResult("email", True)
    except Exception as e:  # noqa: BLE001 best-effort
        log.warning("newsletter email failed: %s", e)
        return DispatchResult("email", False, str(e))


def _post_signed(url: str, payload: dict, secret: str, channel: str) -> DispatchResult:
    if not url or not secret:
        return DispatchResult(channel, False, "url/secret unset")
    if not _RATE.allow(channel):
        return DispatchResult(channel, False, "rate limited")
    body = json.dumps(payload, ensure_ascii=False).encode()
    ts = str(int(time.time()))
    sig = _v2_signature(secret, ts, body)
    headers = {
        "Content-Type": "application/json",
        "X-Webhook-Signature-V2": sig,
        "X-Webhook-Timestamp": ts,
    }
    try:
        resp = httpx.post(url, content=body, headers=headers, timeout=10.0)
        ok = resp.status_code == 200
        return DispatchResult(channel, ok, f"HTTP {resp.status_code}" if not ok else "")
    except Exception as e:  # noqa: BLE001 best-effort
        log.warning("newsletter %s failed: %s", channel, e)
        return DispatchResult(channel, False, str(e))


def send(
    tmpl: NewsletterTemplate,
    *,
    email_to: Optional[str] = None,
    telegram: Optional[Dict[str, str]] = None,
    slack_webhook: Optional[str] = None,
    n8n_url: Optional[str] = None,
) -> List[DispatchResult]:
    """Dispatch a frozen newsletter template across enabled channels.

    Each channel is optional; only configured ones are attempted. Returns a
    list of DispatchResult so callers can log but never abort on failure.
    """
    results: List[DispatchResult] = []
    payload = {"type": tmpl.newsletter_type, "subject": tmpl.subject, "body": tmpl.body}

    if email_to:
        results.append(_send_email(tmpl, email_to))
    if telegram:
        # telegram: {"token","chat_id","thread_id"}
        turl = f"https://api.telegram.org/bot{telegram.get('token','')}/sendMessage"
        body = tmpl.body[:4096]
        data = {"chat_id": telegram.get("chat_id", ""), "text": body}
        if telegram.get("thread_id"):
            data["message_thread_id"] = telegram["thread_id"]
        # Telegram uses its own auth; wrap signature in secret if a webhook secret set
        secret = os.getenv("HERMES_WEBHOOK_SECRET", "")
        if secret:
            results.append(_post_signed(turl, data, secret, "telegram"))
        else:
            # raw best-effort post (still rate-limited)
            if _RATE.allow("telegram"):
                try:
                    r = httpx.post(turl, json=data, timeout=10.0)
                    results.append(DispatchResult("telegram", r.status_code == 200, f"HTTP {r.status_code}"))
                except Exception as e:  # noqa: BLE001
                    results.append(DispatchResult("telegram", False, str(e)))
            else:
                results.append(DispatchResult("telegram", False, "rate limited"))
    if slack_webhook:
        results.append(_post_signed(slack_webhook, payload, os.getenv("SLACK_SECRET", ""), "slack"))
    if n8n_url:
        results.append(_post_signed(n8n_url, payload, os.getenv("N8N_SECRET", ""), "n8n"))
    return results


def unsubscribe(list_addr: str, reason: str = "") -> bool:
    """Record an unsubscribe (Transparent). Best-effort file append."""
    try:
        path = config.STORAGE_DIR / "unsubscribes.log"
        config.STORAGE_DIR.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"{time.time()}\t{list_addr}\t{reason}\n")
        return True
    except Exception as e:  # noqa: BLE001
        log.warning("unsubscribe log failed: %s", e)
        return False
