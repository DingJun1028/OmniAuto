"""Verify 5T-canon proof integrity."""
import json, sys
sys.path.insert(0, r'C:\Project\aistation')
from src import gate5t

with open(r'C:\Project\aistation\5T_canon_proof.json', encoding='utf-8') as f:
    proof = json.load(f)['5T_Canon_Proof']

locked = gate5t.LockedArtifact(
    uuid=proof['traceable']['uuid'],
    kind=proof['tangible']['evidence']['kind'],
    payload=json.dumps(proof, ensure_ascii=False, sort_keys=True),
    hash_lock=proof['trustworthy']['hash_lock'],
    checks=proof['5t_verification_gate_report']['checks']
)

print("Re-verification:", gate5t.verify_locked(locked))
print("UUID:", locked.uuid)
print("Hash:", locked.hash_lock[:20], "...")
print("Kind:", locked.kind)
print("Checks:", locked.checks)
try:
    locked.uuid = "tampered"
    print("⚠️ 修改成功 — 異常")
except Exception as e:
    print(f"✅ 不可篡改驗證通過: {type(e).__name__}")
