"""End-to-end UI-behavior smoke test against a running AI Station server.

Exercises exactly what the Web UI does: POST /api/jobs (with brand_preset),
poll until done, then verify the video endpoint + the job-scoped storage URL
both serve the MP4. Run a server first:  PORT=8123 python -m src.app
"""
import json
import sys
import time
import urllib.request

BASE = "http://localhost:8123"
SCRIPT = (
    "【場景】城市不是替人民設計。\n"
    "【衝突】市民的需求常被專家最佳化取代。\n"
    "【洞察】公共價值來自共創。\n"
    "【方法】用三個共創問題啟動參與。\n"
    "【反思】你上一次被詢問，是什麼時候？"
)


def _req(method, path, data=None):
    url = BASE + path
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(
        url, data=body, method=method,
        headers={"Content-Type": "application/json"} if body else {},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status, json.loads(r.read().decode() or "{}")


def main():
    # 1) submit (UI sends brand_preset)
    st, j = _req("POST", "/api/jobs",
                 {"title": "UI-test", "script": SCRIPT, "brand_preset": "sushi_dr"})
    assert st == 200, f"submit status={st}"
    jid = j["job_id"]
    print(f"[ui] submitted job_id={jid}")

    # 2) poll until terminal
    for _ in range(60):
        st, rec = _req("GET", f"/api/jobs/{jid}")
        if rec["status"] in ("done", "failed"):
            break
        time.sleep(1)
    assert rec["status"] == "done", f"status={rec['status']} result={rec.get('result')}"
    print(f"[ui] done, progress={rec['progress']}")

    # 3) video_url from result + both endpoints serve MP4
    res = json.loads(rec["result"])
    vurl = res["video_url"]
    print(f"[ui] video_url={vurl}")

    # 3a) /api/jobs/{id}/video
    with urllib.request.urlopen(BASE + f"/api/jobs/{jid}/video", timeout=30) as r:
        ct = r.headers.get("Content-Type", "")
        n = len(r.read())
    assert "video/mp4" in ct and n > 1000, f"video endpoint ct={ct} len={n}"
    print(f"[ui] /api/jobs/{jid}/video -> {ct} {n} bytes OK")

    # 3b) the job-scoped storage URL the UI copy button uses
    with urllib.request.urlopen(BASE + vurl, timeout=30) as r:
        ct2 = r.headers.get("Content-Type", "")
        n2 = len(r.read())
    assert "video/mp4" in ct2 and n2 > 1000, f"storage url ct={ct2} len={n2}"
    print(f"[ui] GET {vurl} -> {ct2} {n2} bytes OK")

    print("[ui] ALL UI-BEHAVIOR CHECKS PASSED")


if __name__ == "__main__":
    main()
