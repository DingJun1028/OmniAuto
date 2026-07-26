# AI Station — 交付摘要（v1.0）

> 生成日期：2026-07-26 ｜ 專案：`DingJun1028/aistation`
> 狀態：**可交付**。免費路徑已在 Oracle Always-Free ARM64 永久免費雲端
> 上線並通過線上出片端到端驗收；高畫質/高音質雲端增強與公網域名為
> 可選加強項（見「待辦」）。

---

## 1. 已交付並實測通過

| # | 項目 | 結果 | 證據 |
|---|------|------|------|
| 1 | 7 模組影片管線（parser/tts/visuals/renderer/pipeline/storage/db/metrics） | ✅ | `pytest` **30 passed + 2 skipped** |
| 2 | 免費預設路徑（edge-tts + ffmpeg + Pillow） | ✅ | 線上 5-shot 渲染至 `done` |
| 3 | 壽司博士 Dr. Source 品牌預設（`sushi_dr`）+ DNA 模板 | ✅ | `src/brand.py` / 提案卡 |
| 4 | 多架構容器映像（amd64 + arm64） | ✅ | Docker Hub `dingjunhong1028/aistation:latest` 含兩 arch |
| 5 | VPS 一鍵部署（永久免費雲端） | ✅ | `deploy.yml` CI 跑通，容器 `aistation` 啟動 |
| 6 | 線上出片端到端驗收 | ✅ | `verify.yml` 取回 **754,577 bytes MP4**（`VIDEO_SERVED_OK`） |
| 7 | VPS 本機防火牆/監聽 | ✅ | `diag.yml`：nginx listen 80/443、ufw 開 80/443 |
| 8 | 最佳實踐審計（7 支柱 MECE） | ✅ | rate limit / lazy STORAGE_DIR / temp 清理 / hmac 等 |
| 9 | 提案文件（MD/HTML/PDF） | ✅ | `PROPOSAL.md` / `proposal_card.{html,pdf}` |
| 10 | 部署文檔 | ✅ | `README §11` + `deploy/oracle-free.md` |

---

## 2. 架構

```
腳本/DNA 模板 ──► /api/jobs (FastAPI)
                    │  背景執行緒池 (2 workers)
                    ├─ parser      → 場景切分（內建免費解析）
                    ├─ tts         → edge-tts (免費) | ElevenLabs (雲端, 選填)
                    ├─ visuals     → Pillow 漸層 (免費) | Runway (雲端, 選填)
                    ├─ renderer    → ffmpeg 組裝 + 字幕 + 品牌轉場
                    ├─ storage     → 本地檔案 | S3 (雲端, 選填)
                    └─ db/metrics  → SQLite 溯源 + 指標
                                     ▼
                          Docker (arm64 原生) → nginx 反代 → 公網
```

---

## 3. 待辦（需使用者控制台/金鑰權限 — 非程式碼問題）

### 3.1 公網可達（2 個控制台動作，~2 分鐘）
1. **Oracle Cloud Console → 該 VPS Security List**：加入入站
   `80/tcp` + `443/tcp`（CIDR `0.0.0.0/0`）。Oracle 預設只開 22，
   未開則外部打不到（VPS 本機 ufw 已開，但 VNIC 層安全群組需手動開）。
2. **DNS**：`aistation.esggo.co` A 紀錄 → `161.118.252.147`
   （Cloudflare 或域名商後台）。
- 完成後於 VPS 執行：
  ```bash
  sudo certbot --nginx -d aistation.esggo.co   # 自動簽證 + 轉 443
  ```
- 最終驗收：`curl https://aistation.esggo.co/api/health` 應回 `{"status":"ok"}`。

### 3.2 真雲端增強（任務 B，貼 key 即跑）
- 貼 `RUNWAY_API_KEY` 與 `ELEVENLABS_API_KEY`（遮罩設入 repo Secrets）。
- CI `cloud-integration` job 已備，觸發後跑真實 Runway 出片 + ElevenLabs
  語音，必要時修 `src/visuals.py` / `src/tts.py` 的 API 形狀。

---

## 4. 日常運維指令

```bash
# 重新部署（CI 手動觸發 deploy.yml，免本機 SSH）
gh workflow run deploy.yml -f domain=aistation.esggo.co

# 線上出片驗收
gh workflow run verify.yml -f domain=aistation.esggo.co

# VPS 診斷（防火牆/監聽/公網 IP）
gh workflow run diag.yml

# 本機開發測試
pytest tests/ -q          # 30 passed + 2 skipped
```

---

## 5. 結語

AI Station 已是一套**可獨立運作的免費影片生成管線**，並在永久免費 ARM 雲端
實機上線、真實出片驗收通過。剩餘兩項（公網域名、雲端高畫質/音質）皆為
**可選加強**，且路徑已全數備妥、一經授權即自動執行。
