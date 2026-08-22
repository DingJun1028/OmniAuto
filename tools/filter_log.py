#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
萬能終端輸出過濾轉換器 v2 (Universal Terminal Log Filter + Diagnostics)
==========================================================================
把「貼整段 PowerShell / bash 終端機輸出（含錯誤回聲、ANSI、tree 符號、
重複提示符、亂碼）」這類髒輸入，自動：
  [A] 過濾 → 只留有效指令 + 日誌證據
  [B] 亂碼根治 → 修 BOM / CRLF / 替換字(U+FFFD) / cp950↔utf8 混炸 / 零寬字元
  [C] 報錯除錯 → 從日誌提取根因 + 給修復建議

用法:
  python3 filter_log.py input.txt
  python3 filter_log.py input.txt --mode commands|logs|diagnose
  cat dirty.txt | python3 filter_log.py -

原則: 寧可漏過濾也不偽造。無法判斷的行進「未分類」。
"""
import sys
import re
import argparse
import unicodedata

# ============ 1. 亂碼根治 ============
def decode_fix(text: str) -> str:
    """根治常見終端亂碼。"""
    # 去 BOM
    if text.startswith("\ufeff"):
        text = text[1:]
    # 去零寬 / 控制字元 (保留 \n \r \t)
    cleaned = []
    for ch in text:
        if ch in ("\n", "\r", "\t"):
            cleaned.append(ch)
        elif unicodedata.category(ch) in ("Cf", "Cs", "Co"):
            continue  # 控制/代理/私用 → 丟
        elif ord(ch) == 0xFFFD:
            cleaned.append("?")  # 替換字 → 標記缺失
        else:
            cleaned.append(ch)
    text = "".join(cleaned)
    # CRLF → LF
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # cp950 典型毀損: 全形?後接半形英數 → 已是 unicode 不用動; 這裡只標注
    return text

# ============ 2. 噪聲過濾 ============
NOISE = [
    re.compile(r"無法辨識\s*'[^']*'\s*詞彙"),
    re.compile(r"CategoryInfo\s*:"),
    re.compile(r"FullyQualifiedErrorId\s*:"),
    re.compile(r"^\s*\+\s*位於\s*線路"),
    re.compile(r"^\s*\+\s*~+"),
    re.compile(r"ParserError\s*:"),
    re.compile(r"CommandNotFoundException"),
    re.compile(r"ParameterBindingException"),
    re.compile(r"ParentContainsErrorRecordException"),
    re.compile(r"UnexpectedToken"),
    re.compile(r"MissingEndParenthesisInExpression"),
    re.compile(r"MissingArgument"),
    re.compile(r"運算式中遺失"),
    re.compile(r"運算式或陳述式中有未預期的"),
    re.compile(r"參數清單中遺失引數"),
    re.compile(r"參數名稱不明確"),
    re.compile(r"^PS\s+C:\\.*>\s*$"),
    re.compile(r"載入個人與系統設定檔花了\s*\d+\s*毫秒"),
    re.compile(r"^PS\s+C:\\.*>\s*PS\s+C:\\"),
    re.compile(r"^[\s├└│─●►▶█░▒▓│]+$"),
]
PROMPT_LEAD = re.compile(r"^(PS\s+C:\\Users\\[^>]*>\s*|[a-zA-Z]:\\>|\$\s*|>\s*)")
COMMAND_HINT = re.compile(
    r"^\s*(ssh|scp|git|cd|curl|wget|pm2|sudo|systemctl|nginx|journalctl|cat|ls|find|grep|python3?|node|docker|kubectl|gh|npm|pnpm)\b"
)
LOG_HINT = re.compile(
    r"(journalctl|cloudflared|nginx\[|systemd\[|ERR\s|emerg|notice|WARN|error=|connection refused|"
    r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}|\b\d{4}/\d{2}/\d{2}\b|originService=|dial tcp|"
    r"Active:|Loaded:|Main PID:|Tasks:|CGroup:|Memory:|CPU:|Process:|ExecReload)"
)
ANSI_ESC = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")


def clean_line(raw: str) -> str:
    line = ANSI_ESC.sub("", raw)
    line = line.replace(" ", " ")
    return line.strip()


def is_noise(line: str) -> bool:
    return any(p.search(line) for p in NOISE)


def classify(line: str):
    cleaned = clean_line(line)
    if not cleaned or is_noise(cleaned):
        return ("skip", cleaned)
    body = PROMPT_LEAD.sub("", cleaned).strip()
    if not body:
        return ("skip", cleaned)
    if COMMAND_HINT.search(body):
        # 排除 nginx 日誌行 (nginx: the configuration file ...)
        if re.match(r"^nginx:\s+(the configuration|configuration file)", body):
            return ("log", body)
        return ("command", body)
    if LOG_HINT.search(body):
        return ("log", body)
    if re.search(r"^(Loaded|Active|Docs|Process|Main PID|Tasks|CGroup|Memory|CPU):", body):
        return ("log", body)
    return ("unknown", body)


# ============ 3. 報錯除錯 ============
DIAG_RULES = [
    {
        "id": "conn_refused",
        "match": re.compile(r"connection refused|dial tcp [\d.:]+: connect: connection refused"),
        "root": "目標埠口無服務在聽 (connection refused)",
        "advice": "用 `curl -sS -m3 http://<host>:<port>/ -o /dev/null -w '%{http_code}'` 確認；"
                  "若 refused → `sudo systemctl status <svc>` / `pm2 list` 查進程是否掛；"
                  "啟動: `sudo systemctl start <svc>` 或 `pm2 restart <app>`。",
    },
    {
        "id": "nginx_proxy_arg",
        "match": re.compile(r"invalid number of arguments in .proxy_set_header. directive in (.+?):(\d+)"),
        "root": "nginx 設定檔 proxy_set_header 參數數量錯 (語法錯)",
        "advice": "開 `nginx -t` 定位檔:行 (如 oa.esggo.co.conf:8)；"
                  "proxy_set_header 須 `proxy_set_header <field> <value>;` 兩參數，"
                  "檢查是否漏空格/引號/換行斷裂。修完 `sudo nginx -t && sudo systemctl reload nginx`。",
    },
    {
        "id": "nginx_reload_fail",
        "match": re.compile(r"Reload failed for nginx|status=1/FAILURE"),
        "root": "nginx reload 失敗 (設定檔有錯)",
        "advice": "先 `sudo nginx -t` 看具體行；勿盲目 restart，先修 conf 再 reload。",
    },
    {
        "id": "cloudflared_origin",
        "match": re.compile(r"Unable to reach the origin service.*originService=(http://[\d.:]+)"),
        "root": "cloudflared 連不到後端 origin (tunnel 源站死)",
        "advice": "擷取 originService 的 host:port (如 127.0.0.1:8421)，"
                  "在 VPS 本機查該服務狀態並重啟；cloudflared 本身不用重啟，重啟源站即可。",
    },
    {
        "id": "ambiguous_param",
        "match": re.compile(r"參數名稱不明確|AmbiguousParameter"),
        "root": "PowerShell 指令參數縮寫歧義 (如 `-o` 被當 Get-Process 的 -OutVariable)",
        "advice": "不要從聊天/終端回聲複製整段；只貼純指令。確認 `-o` 是 ssh 的參數而非被 PowerShell 截走。",
    },
]


def diagnose(logs: list) -> list:
    """從日誌行提取根因 + 建議。"""
    findings = []
    for rule in DIAG_RULES:
        for line in logs:
            m = rule["match"].search(line)
            if m:
                extra = ""
                if rule["id"] == "nginx_proxy_arg" and m.groups():
                    extra = f" (檔案: {m.group(1)} 行 {m.group(2)})"
                if rule["id"] == "cloudflared_origin" and m.groups():
                    extra = f" (origin = {m.group(1)})"
                findings.append({
                    "id": rule["id"],
                    "root": rule["root"] + extra,
                    "advice": rule["advice"],
                    "sample": line[:160],
                })
                break  # 同規則只報一次
    return findings


# ============ 4. 主流程 ============
def process(text: str):
    text = decode_fix(text)
    commands, logs, unknowns = [], [], []
    for raw in text.splitlines():
        kind, body = classify(raw)
        if kind == "skip" or not body:
            continue
        if kind == "command":
            if body not in commands:
                commands.append(body)
        elif kind == "log":
            logs.append(body)
        else:
            if body not in unknowns:
                unknowns.append(body)
    return commands, logs, unknowns


def main():
    ap = argparse.ArgumentParser(description="萬能終端輸出過濾轉換器 v2")
    ap.add_argument("input", nargs="?", default="-")
    ap.add_argument("--mode", choices=["all", "commands", "logs", "diagnose"], default="all")
    args = ap.parse_args()

    if args.input == "-":
        text = sys.stdin.read()
    else:
        with open(args.input, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()

    commands, logs, unknowns = process(text)
    diags = diagnose(logs) if (args.mode in ("all", "diagnose")) else []

    if args.mode in ("all", "commands") and commands:
        print("=" * 60); print("【A】有效指令 (可直接複用)"); print("=" * 60)
        for c in commands:
            print(c)
    if args.mode in ("all", "logs") and logs:
        print("=" * 60); print("【B】日誌證據 (診斷用)"); print("=" * 60)
        for l in logs:
            print(l)
    if args.mode == "all" and unknowns:
        print("=" * 60); print("【C】未分類 (人工確認)"); print("=" * 60)
        for u in unknowns:
            print(u)
    if args.mode in ("all", "diagnose") and diags:
        print("=" * 60); print("【D】報錯除錯 (根因 + 建議)"); print("=" * 60)
        for d in diags:
            print(f"[{d['id']}] {d['root']}")
            print(f"  建議: {d['advice']}")
            print(f"  樣本: {d['sample']}")
    if args.mode == "all" and not (commands or logs or unknowns or diags):
        print("(無可提取內容)")


if __name__ == "__main__":
    main()
