"""Weekly swarm report generator (§23 §24 P1 newsletter integration).

Builds the cross-repo KPI report via src.kpi and dispatches it through
src.newsletter. Designed to be invoked by n8n (cron) or manually:

    python scripts/weekly_report.py --dry-run        # print markdown, no send
    python scripts/weekly_report.py --channels telegram,slack
    python scripts/weekly_report.py --pairing 95 --entropy 0.08 --security 0

Swarm KPIs (cross_unit_pairing / handoff_time / defect_rate / idea_realization
/ satisfaction / security_events / entropy) are passed as real measured
values from the caller — never fabricated inside this script.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow running as a standalone script from repo root.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import kpi, newsletter  # noqa: E402
import os  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="OA-Team weekly swarm report")
    ap.add_argument("--dry-run", action="store_true", help="print markdown, do not send")
    ap.add_argument("--channels", default="", help="comma list: telegram,slack,email,smtp")
    ap.add_argument("--pairing", type=float, help="cross_unit_pairing %% (real measured)")
    ap.add_argument("--handoff", type=float, help="handoff_time hours")
    ap.add_argument("--defect", type=float, help="defect_rate %%")
    ap.add_argument("--idea", type=float, help="idea_realization %%")
    ap.add_argument("--satisfaction", type=float, help="satisfaction /5")
    ap.add_argument("--security", type=int, help="security_events count")
    ap.add_argument("--entropy", type=float, help="entropy value")
    args = ap.parse_args()

    overrides = {}
    for cli_key, kpi_key in (
        ("pairing", "cross_unit_pairing"),
        ("handoff", "handoff_time"),
        ("defect", "defect_rate"),
        ("idea", "idea_realization"),
        ("satisfaction", "satisfaction"),
        ("security", "security_events"),
        ("entropy", "entropy"),
    ):
        v = getattr(args, cli_key)
        if v is not None:
            overrides[kpi_key] = v

    report = kpi.build_weekly_report(**overrides)
    md = kpi.render_weekly_markdown(report)

    if args.dry_run:
        print(md)
        print("\n[DRY-RUN] not sent. channels would be:", args.channels or "(none configured)")
        return 0

    channels = [c.strip() for c in args.channels.split(",") if c.strip()]
    if not channels:
        print(md)
        print("\n[NO CHANNELS] set --channels or run with --dry-run")
        return 0

    subject = f"萬能蜂群週報 — 總評 {report['overall']}"
    tmpl = newsletter.build_template("weekly_swarm", subject, md)
    send_kwargs: dict = {}
    if "telegram" in channels:
        send_kwargs["telegram"] = {
            "token": os.getenv("TELEGRAM_BOT_TOKEN", ""),
            "chat_id": os.getenv("TELEGRAM_CHAT_ID", ""),
            "thread_id": os.getenv("TELEGRAM_THREAD_ID", ""),
        }
    if "slack" in channels:
        send_kwargs["slack_webhook"] = os.getenv("SLACK_WEBHOOK_URL", "")
    if "n8n" in channels:
        send_kwargs["n8n_url"] = os.getenv("N8N_WEBHOOK_URL", "")
    if "email" in channels:
        send_kwargs["email_to"] = os.getenv("NEWSLETTER_EMAIL_TO", "")

    results = newsletter.send(tmpl, **send_kwargs)
    for r in results:
        print(f"[{'OK' if r.ok else 'FAIL'}] channel={r.channel} detail={r.detail}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
