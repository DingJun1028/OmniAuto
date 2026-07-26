# AI Station — 全自動影音生產線

> 把一段腳本，變成一支帶字幕、帶品牌開場、可立即分發的影片。
> 預設 **零雲端成本**（edge-tts + ffmpeg + Pillow），需要更高品質時再接雲端金鑰。

AI Station 是一套以 FastAPI 為控制核心的影音生產管線，把「寫腳本」到「出片」之間的
解析、語音、畫面、剪輯、字幕、發布、可觀測性，全部自動化。它為
**創價未來｜壽司博士 Dr. Source**（主持人 楊坤修博士 / 善向永續 ESG Sunshine）內建了
品牌預設，也能透過 n8n webhook 接進任何排程或自動化流程。

---

## 1. 它能做什麼

- **腳本 → 鏡頭**：內建解析器把每句話切成一個鏡頭；若貼上品牌 DNA 標記
  （`【場景】【衝突】【洞察】【方法】【反思】`），自動產生一拍一鏡的 on-brand 結構。
- **語音**：預設 edge-tts（免費、多語）；金鑰就緒時可切 ElevenLabs。
- **畫面**：預設 Pillow 漸層（自動套用品牌色）；金鑰就緒時可接 Runway 生成 B-roll。
- **剪輯 + 字幕**：ffmpeg 把音檔與畫面合成，字幕以「卡拉OK式」逐字同步燒入。
- **品牌開場**：自動產生壽司博士深藍→暖金開場 slate。
- **發布**：本地儲存（預設）+ 選用 S3。
- **可觀測性**：`/api/metrics` 聚合成功率、平均渲染、品牌分布；Web UI 即時儀表板。

---

## 2. 架構（7 模組，對應 IDEA 規劃書）

| # | 模組 | 檔案 | 預設（免費） | 雲端增強 |
|---|------|------|--------------|----------|
| 1 | 編排中心 | `src/pipeline.py` / `src/app.py` | FastAPI + 背景執行緒池 | — |
| 2 | 文字解析（LLM 腦） | `src/parser.py` | 內建句法解析器 | OpenAI GPT-4o |
| 3 | 語音合成 (TTS) | `src/tts.py` | edge-tts | ElevenLabs |
| 4 | 視覺生成 | `src/visuals.py` | Pillow 漸層 | Runway |
| 5 | 渲染引擎 | `src/renderer.py` | ffmpeg + 同步字幕 | — |
| 6 | 雲端儲存 | `src/storage.py` | 本地 `/storage` | S3 |
| 7 | 溯源/作業庫 | `src/db.py` | SQLite | NoCodeBackend |

所有雲端整合都是 **可選**：金鑰留白就走免費路徑，且任一雲端失敗都會優雅回落（fallback）。

---

## 3. 快速開始

```bash
# 1. 安裝
pip install -e .            # 含 edge-tts, fastapi, ffmpeg 由系統提供
# 或：pip install -e ".[s3]"   # 需要 S3 發布時

# 2. ffmpeg 必須在 PATH（影片合成用）
ffmpeg -version

# 3. 啟動
python -m src.app           # 或 uvicorn src.app:app --port 8000
# 打開 http://localhost:8000 即可看到 Web UI
```

用 Docker：

```bash
docker build -t ai-station .
docker run -p 8000:8000 ai-station
```

---

## 4. 使用方式

### Web UI
開啟 `http://localhost:8000`：貼腳本 → 一鍵生成 → 即時看進度與成片，下方有生產線指標卡。

### REST API

| 方法 | 路徑 | 說明 |
|------|------|------|
| GET | `/api/health` | 健康檢查 + feature 旗標 |
| GET | `/api/metrics` | 生產線指標（總數/成功率/平均渲染/品牌分布） |
| POST | `/api/jobs` | 提交作業，立即回傳 `queued` + `job_id` |
| GET | `/api/jobs` | 作業列表 |
| GET | `/api/jobs/{id}` | 單一作業狀態 |
| GET | `/api/jobs/{id}/video` | 成片檔（status=done 才有效） |
| GET | `/api/series` | 壽司博士欄目 + 母題 |
| GET | `/api/brand` | 品牌預設 |
| POST | `/webhook/n8n` | n8n webhook（同步回傳結果，含 `ok` 旗標） |

### n8n webhook 範例
n8n 用 HTTP Request 節點 POST 到 `/webhook/n8n`，body `{ "title", "script", "brand_preset": "sushi_dr" }`，
回傳 `{ "job_id", "status", "ok", "video_url", "shots", "error" }`。`ok=true` 表示成功出片。

### 品牌 DNA 腳本範例
```
【場景】城市不是替人民設計。
【衝突】市民的需求常被專家最佳化取代。
【洞察】公共價值來自共創。
【方法】用三個共創問題啟動參與。
【反思】你上一次被詢問，是什麼時候？
```

---

## 5. 設定（`.env`）

複製 `.env.example` 為 `.env`。所有金鑰**選填**——留白即走免費路徑。

| 變數 | 用途 | 預設 |
|------|------|------|
| `WEBHOOK_SECRET` | webhook 認證（常數時間比對） | 空白=開放 |
| `OPENAI_API_KEY` | 啟用 GPT-4o 鏡頭規劃 | 空白=內建解析器 |
| `ELEVENLABS_API_KEY` | 啟用 ElevenLabs 語音 | 空白=edge-tts |
| `RUNWAY_API_KEY` | 啟用 Runway B-roll | 空白=Pillow 漸層 |
| `AWS_*` | S3 發布（需 `[s3]` extra） | 空白=本地 |
| `NCBDB_*` | NoCodeBackend 溯源鏡像 | 空白=僅本地 SQLite |
| `VIDEO_WIDTH/HEIGHT/FPS` | 輸出解析度 | 1280×720×30 |

---

## 6. 安全與可靠性

- **Webhook 認證**：`WEBHOOK_SECRET` 啟用後，以 `X-AI-Station-Key` header 或 `?key=` 校驗，
  使用 `hmac.compare_digest` 常數時間比對，避免時序側信道。
- **路徑穿越防護**：`/storage/{path}` 與 `/video` 皆 resolve 後確認在 `STORAGE_DIR` 內。
- **背景作業不卡死**：渲染失敗會寫入 `failed` + 紀錄錯誤，不會永遠卡在 `queued`。
- **雲端優雅回落**：Runway / OpenAI 失敗自動回到免費路徑，不中斷生產。

---

## 7. 開發與測試

```bash
pip install -e ".[dev]"
pytest                       # 30 測試（config/parser/tts/renderer/db/api/security/
                             #        integration/runway/openai/webhook/metrics）
```

- `test_integration_render_runs_ffmpeg` 跑真 ffmpeg；無 ffmpeg 時自動 skip。
- 渲染類測試用 `isolated_state` fixture，把 `jobs.db` 與 `storage/` 導向暫存目錄，不污染 repo。
- 目前 **30 測試全綠**（CI 含 ffmpeg + Noto CJK 字體）。

---

## 8. 可觀測性

`GET /api/metrics` 回傳：

```json
{
  "total": 12,
  "by_status": {"done": 10, "failed": 1, "rendering": 1},
  "success_rate": 90.9,
  "avg_render_seconds": 18.3,
  "top_brands": [{"brand": "sushi_dr", "count": 9}, {"brand": "default", "count": 3}],
  "last_24h_count": 5,
  "brand_breakdown": {"sushi_dr": 9, "default": 3}
}
```

Web UI 的「③ 生產線指標」卡片每 5 秒刷新這些數字。

---

## 9. 文件結構

```
src/
  app.py        控制核心（FastAPI 路由）
  pipeline.py   編排（背景執行緒池、job 生命週期）
  parser.py     文字解析（內建 / OpenAI / DNA）
  tts.py        語音合成
  visuals.py    視覺生成（漸層 / Runway）
  renderer.py   ffmpeg 渲染 + 同步字幕
  storage.py    本地 / S3 發布
  db.py         SQLite 作業庫 + 溯源鏡像
  metrics.py    指標聚合
  brand.py      壽司博士品牌預設
  config.py     設定 + feature 旗標
web/index.html  Web UI（提交 / 監控 / 指標）
tests/         pytest 套件
```

---

## 10. 路線圖

- [x] 7 支柱 MECE 最佳實踐（正確性/安全/可維護/效能/擴充/可觀測/測試）
- [x] 背景作業失敗標記、webhook 常數時間比對、S3 超時防僵
- [x] 按 `shot.index` 顯式排序防禦、webhook `ok` 旗標、metrics 儀表板
- [x] Docker Hub 自動推映像（`DOCKERHUB_*` Secrets → CI 建置並推送 `docker.io/dingjunhong1028/aistation:latest`）
- [ ] 真 Runway B-roll 實測（待 `RUNWAY_API_KEY`）

---

## 11. 部署到 VPS（esggo 場域）

容器映像已推送：**`docker.io/dingjunhong1028/aistation:latest`**。
`deploy/` 目錄提供可複用的生產堆疊（已驗證語法）：

```
deploy/
  docker-compose.yml              # pull 映像，:8000 僅綁 localhost，volume 掛 ./storage，含 healthcheck
  nginx/aistation.esggo.co.conf   # 反向代理 + X-Forwarded-*（HTTP 區塊；HTTPS 區塊註解待 certbot）
  deploy.sh USER@HOST [DOMAIN]    # rsync + compose up -d + 裝 nginx site + 健康檢查
  .env.example                    # 伺服器端環境變數範本（複製為 .env，勿進版控）
```

**本機一鍵部署**（需本機能 SSH 進 VPS，且 VPS 已裝 docker/compose + nginx）：

```bash
# 1) 在 VPS 上：把本機公鑰加入 authorized_keys（只需一次）
#    cat ~/.ssh/id_rsa_esggo.pub | ssh USER@HOST 'cat >> ~/.ssh/authorized_keys'

# 2) 在 VPS 上建立伺服器端 .env（金鑰選填，勿進 git）
#    rsync -a deploy/.env.example USER@HOST:~/aistation/deploy/.env   # 再補填金鑰

# 3) 本機執行部署
./deploy/deploy.sh USER@HOST aistation.esggo.co

# 4) DNS：aistation.esggo.co A/AAAA -> VPS IP；HTTPS：sudo certbot --nginx -d aistation.esggo.co
```

**不登入 VPS 的做法**：把 `deploy/` 整包交給有權限的人，於 VPS 上
`docker compose pull && docker compose up -d`，再把 `nginx/...conf` 啟用即可。

所有雲端金鑰選填；留白即走免費路徑（edge-tts + ffmpeg + Pillow）。
