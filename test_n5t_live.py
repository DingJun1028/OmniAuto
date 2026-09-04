"""Real-world test: dispatch a 5T-canon proof via the live Hermes webhook.

Verifies the dual-channel fallback actually works:
  1. Sends primary `5t_canon_proof` envelope (HMAC-V2 signed)
  2. Sends legacy `video_done` envelope (HMAC-V2 signed) so existing
     gateway routing forwards it to Telegram.

Reads HERMES_WEBHOOK_URL + HERMES_WEBHOOK_SECRET from .env.
"""
import json, sys, os
sys.path.insert(0, r"C:\Project\aistation")
from src import n5t

if __name__ == "__main__":
    print("=" * 70)
    print("  LIVE TEST — 5T-canon proof dual-envelope dispatch")
    print("=" * 70)
    print(f"  URL:    {n5t.HERMES_WEBHOOK_URL}")
    print(f"  Secret: {'<set, len=' + str(len(n5t.HERMES_WEBHOOK_SECRET)) + '>' if n5t.HERMES_WEBHOOK_SECRET else '<empty>'}")

    result = n5t.notify_5t_canon_proof(
        kind="5T-Canon-Proof-LiveTest",
        uuid="test-live-001",
        hash_lock="a1b2c3d4e5f6" + "0" * 52,
        source_origin="OA-Team-30-Swarm::test-live",
        pillars_passed={
            "Tangible": True, "Traceable": True, "Trackable": True,
            "Transparent": True, "Trustworthy": True,
        },
        result="PASSED",
    )

    print()
    print(f"  Delivered: {result['delivered']}")
    print(f"  Primary:   status={result['primary_event'].get('status')} resp={result['primary_event'].get('response', '')[:80]}")
    print(f"  Legacy:    status={result['legacy_event'].get('status')} resp={result['legacy_event'].get('response', '')[:80]}")
    print()
    if result["delivered"]:
        print("  ✅ At least one channel accepted the notification")
    else:
        print("  ❌ All channels failed")
