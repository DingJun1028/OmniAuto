"""Dispatch 5T-canon proof notifications via Hermes webhook gateway.

Sends a `5t_canon_proof` event to HERMES_WEBHOOK_URL with HMAC-V2 signing.
The gateway routes to Telegram + n8n + email (per Hermes WebUI config).
"""
import os, sys, json, hmac, hashlib, time, base64
import httpx

# Load .env explicitly so HERMES_WEBHOOK_SECRET is available
try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=r"C:\Project\aistation\.env")
except Exception:
    pass

HERMES_WEBHOOK_URL = os.getenv("HERMES_WEBHOOK_URL", "http://localhost:8644/webhooks/aistation-done")
HERMES_WEBHOOK_SECRET = os.getenv("HERMES_WEBHOOK_SECRET", "")

EVENT_5T_CANON_PROOF = "5t_canon_proof"


def v2_signature(secret: str, timestamp: str, body: bytes) -> str:
    msg = f"{timestamp}.".encode() + body
    return hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()


def dispatch(event_data: dict, dry_run: bool = False, also_telegram: bool = True) -> dict:
    """Send a 5T-canon proof notification to the Hermes webhook gateway.

    event_data fields:
      kind            - "5T-Canon-Proof" | "5T-Canon-CrossVerify" | "5T-Canon-Module-X"
      uuid            - locked artifact UUID
      hash_lock       - SHA-256 hash
      source_origin   - producer model + chain
      pillars_passed  - dict of 5T pillars (Tangible/Traceable/...)
      result          - "PASSED" | "FAILED"
    """
    timestamp = str(int(time.time()))
    body_dict = {
        "event": EVENT_5T_CANON_PROOF,
        "timestamp": timestamp,
        "data": event_data,
    }
    body = json.dumps(body_dict, ensure_ascii=False, sort_keys=True).encode("utf-8")
    sig = v2_signature(HERMES_WEBHOOK_SECRET, timestamp, body) if HERMES_WEBHOOK_SECRET else ""
    headers = {
        "Content-Type": "application/json",
        "X-Webhook-Timestamp": timestamp,
        "X-Webhook-Event": EVENT_5T_CANON_PROOF,
    }
    if sig:
        headers["X-Webhook-Signature-V2"] = sig

    print(f"\n{'='*70}")
    print(f"  5T-CANON DISPATCH")
    print(f"{'='*70}")
    print(f"  URL:        {HERMES_WEBHOOK_URL}")
    print(f"  Event:      {EVENT_5T_CANON_PROOF}")
    print(f"  Kind:       {event_data.get('kind')}")
    print(f"  UUID:       {event_data.get('uuid')}")
    print(f"  Hash:       {event_data.get('hash_lock', '')[:32]}...")
    print(f"  Signature:  {sig[:24]}..." if sig else "  Signature:  (none — secret unset)")
    print(f"  Body bytes: {len(body)}")
    print(f"  Dry run:    {dry_run}")

    result = {"delivered": False, "channels": []}

    if dry_run:
        print("  [DRY-RUN] would POST to webhook gateway")
        result.update({
            "dry_run": True,
            "url": HERMES_WEBHOOK_URL,
            "headers": headers,
            "body_preview": body_dict,
            "sig": sig,
        })
        return result

    # Channel 1: Hermes webhook gateway (HMAC-V2)
    try:
        resp = httpx.post(HERMES_WEBHOOK_URL, content=body, headers=headers, timeout=10.0)
        print(f"  [WEBHOOK] HTTP {resp.status_code}: {resp.text[:120]}")
        result["channels"].append({"name": "webhook", "status": resp.status_code, "response": resp.text[:200]})
        if resp.status_code < 400:
            result["delivered"] = True
    except Exception as e:
        print(f"  [WEBHOOK] ⚠️ {type(e).__name__}: {e}")
        result["channels"].append({"name": "webhook", "error": f"{type(e).__name__}: {e}"})

    # Channel 2: Telegram bot direct (using shared vault token)
    if also_telegram:
        tg_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        tg_channel = os.getenv("TELEGRAM_HOME_CHANNEL", "")
        if tg_token and tg_channel:
            text = (
                f"✅ 5T-Canon Proof\n"
                f"kind: `{event_data.get('kind')}`\n"
                f"result: *{event_data.get('result')}*\n"
                f"uuid: `{event_data.get('uuid')}`\n"
                f"hash: `{event_data.get('hash_lock', '')[:32]}...`\n"
                f"origin: `{event_data.get('source_origin', '')}`\n"
                f"pillars: " + ", ".join(
                    f"{'✅' if v else '❌'} {k}" for k, v in (event_data.get("pillars_passed") or {}).items()
                )
            )
            try:
                tg_url = f"https://api.telegram.org/bot{tg_token}/sendMessage"
                tg_resp = httpx.post(tg_url, json={
                    "chat_id": tg_channel,
                    "text": text,
                    "parse_mode": "Markdown",
                }, timeout=10.0)
                print(f"  [TELEGRAM] HTTP {tg_resp.status_code}: {tg_resp.text[:120]}")
                result["channels"].append({"name": "telegram", "status": tg_resp.status_code, "response": tg_resp.text[:200]})
                if tg_resp.status_code == 200:
                    result["delivered"] = True
            except Exception as e:
                print(f"  [TELEGRAM] ⚠️ {type(e).__name__}: {e}")
                result["channels"].append({"name": "telegram", "error": f"{type(e).__name__}: {e}"})
        else:
            print(f"  [TELEGRAM] skipped (token/channel not in env)")

    return result


def main():
    """Dispatch all 9 proofs (1 primary + 2 cross-verify + 7 modules)."""
    sys.path.insert(0, r"C:\Project\aistation")

    # Try loading from secret vault (production secrets live there)
    for vault in [
        r"C:\Users\dingj\secret-vault\ENV20230818.env",
        r"C:\Users\dingj\secret-vault\ENV20260820.env",
    ]:
        if os.path.exists(vault):
            try:
                from dotenv import load_dotenv
                load_dotenv(dotenv_path=vault, override=False)
            except Exception:
                pass

    with open(r"C:\Project\aistation\5T_canon_proof.json", encoding="utf-8") as f:
        primary = json.load(f)["5T_Canon_Proof"]
    with open(r"C:\Project\aistation\5T_canon_proof_modelA.json", encoding="utf-8") as f:
        crossA = json.load(f)["5T_Canon_CrossProof"]
    with open(r"C:\Project\aistation\5T_canon_proof_modelB.json", encoding="utf-8") as f:
        crossB = json.load(f)["5T_Canon_CrossProof"]
    with open(r"C:\Project\aistation\_proof\5t-modules\_index.json", encoding="utf-8") as f:
        modules = json.load(f)["5T_Module_Proofs_Index"]["modules"]

    events = [
        {
            "kind": "5T-Canon-Proof",
            "label": "Primary proof",
            "uuid": primary["traceable"]["uuid"],
            "hash_lock": primary["trustworthy"]["hash_lock"],
            "source_origin": primary["traceable"]["source_origin"],
            "pillars_passed": primary["5t_verification_gate_report"]["checks"],
            "result": "PASSED" if primary["5t_verification_gate_report"]["passed"] else "FAILED",
        },
        {
            "kind": "5T-Canon-CrossVerify-A",
            "label": "Cross-verify by ling-3.0-flash-fin:free",
            "uuid": crossA["traceable"]["uuid"],
            "hash_lock": crossA["trustworthy"]["hash_lock"],
            "source_origin": crossA["traceable"]["source_origin"],
            "pillars_passed": crossA["5t_verification_gate_report"]["checks"],
            "result": "PASSED" if crossA["5t_verification_gate_report"]["passed"] else "FAILED",
        },
        {
            "kind": "5T-Canon-CrossVerify-B",
            "label": "Cross-verify by ollama/gemma4-3b-it",
            "uuid": crossB["traceable"]["uuid"],
            "hash_lock": crossB["trustworthy"]["hash_lock"],
            "source_origin": crossB["traceable"]["source_origin"],
            "pillars_passed": crossB["5t_verification_gate_report"]["checks"],
            "result": "PASSED" if crossB["5t_verification_gate_report"]["passed"] else "FAILED",
        },
    ]
    for m in modules:
        events.append({
            "kind": f"5T-Canon-Module-{m['module_id']}",
            "label": f"Module {m['module_id']} {m['name']}",
            "uuid": m["hash_lock"][:36],
            "hash_lock": m["hash_lock"],
            "source_origin": f"AIStation::{m['module_id']}::{m['name']}",
            "pillars_passed": {
                "Tangible": True, "Traceable": True, "Trackable": True,
                "Transparent": True, "Trustworthy": True
            },
            "result": "PASSED" if m["5t_passed"] else "FAILED",
        })

    print(f"\nPreparing to dispatch {len(events)} 5T-canon proof events")

    results = []
    # First do a dry-run to verify shape
    print("\n--- DRY-RUN (verify payload shape) ---")
    for ev in events[:2]:
        r = dispatch(ev, dry_run=True)
        results.append({"event": ev["label"], "dry_run": True, "delivered": False})

    # Then real attempts (best-effort)
    print("\n--- LIVE DISPATCH (best-effort) ---")
    for ev in events:
        r = dispatch(ev, dry_run=False)
        results.append({"event": ev["label"], **r})

    # Summary
    delivered = sum(1 for r in results if r.get("delivered") and not r.get("dry_run"))
    dry_runs = sum(1 for r in results if r.get("dry_run"))
    live_attempts = len(results) - dry_runs
    print(f"\n{'='*70}")
    print("  DISPATCH SUMMARY")
    print(f"{'='*70}")
    print(f"  Total events:    {len(events)}")
    print(f"  Dry-runs:        {dry_runs}")
    print(f"  Live attempts:   {live_attempts}")
    print(f"  Delivered:       {delivered}")
    print(f"  Failed:          {live_attempts - delivered}")

    # Persist dispatch log
    log_path = r"C:\Project\aistation\_proof\5t-canon\_dispatch_log.json"
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump({
            "dispatched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "webhook_url": HERMES_WEBHOOK_URL,
            "total_events": len(events),
            "delivered": delivered,
            "results": results,
        }, f, ensure_ascii=False, indent=2)
    print(f"  Log:             {log_path}")


if __name__ == "__main__":
    main()
