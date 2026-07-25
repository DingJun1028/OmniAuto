# AI Station · 全自動影音生產線

一個把「腳本」自動變成「YouTube 影片」的控制中心 (control center)，對應
`IDEA.md` 中規劃的七大模組。預設**零 API Key** 即可全自動運作（使用 Microsoft
edge-tts + ffmpeg + Pillow 本地免費引擎），雲端服務（OpenAI / ElevenLabs /
Runway / S3 / NCBDB）全部以「可插拔設定」形式接上，填了 key 就自動啟用。

## 對應 IDEA.md 模組

| # | 模組 | 免費預設 | 雲端啟用 (設 env) |
|---|------|----------|-------------------|
| 1 | 流程中樞 Orchestration | 內建 FastAPI + 管線引擎 | 可接 n8n Webhook |
| 2 | 文本解析 LLM Brain | 規則式分句解析器 | `OPENAI_API_KEY` |
| 3 | 語音引擎 TTS | edge-tts (多語言) | `ELEVENLABS_API_KEY` |
| 4 | 視覺生成 Visuals | Pillow 漸層 + Ken-Burns | `RUNWAY_API_KEY` |
| 5 | 渲染引擎 Rendering | ffmpeg (headless) | — |
| 6 | 雲端存儲 Storage | 本機 `./storage` | `AWS_*` |
| 7 | 溯源日誌 Database | 本地 SQLite | `NCBDB_BASE_URL` |

## 快速開始

```bash
# 1. 建立虛擬環境並安裝依賴
python -m venv .venv
source .venv/Scripts/activate        # Windows
pip install -r requirements.txt

# 2. (選用) 複製 .env.example 為 .env 並填入雲端 key
cp .env.example .env

# 3. 啟動 AI Station
python run.py
# 或： uvicorn src.app:app --reload --port 8000
```

打開 http://localhost:8000 ，貼上腳本，點「一鍵生成影片」即可。

## 透過 API 驅動 (供 n8n Webhook 串接)

```bash
# 提交腳本 -> 同步回傳 job 結果
curl -X POST http://localhost:8000/api/jobs \
  -H 'Content-Type: application/json' \
  -d '{"title":"宇宙簡史","script":"宇宙浩瀚無垠。科學家持續探索。"}'

# n8n Webhook 入口（同步回傳 job_id / status / video_url）
curl -X POST http://localhost:8000/webhook/n8n \
  -H 'Content-Type: application/json' \
  -d '{"title":"每日快報","script":"今天的新聞。我們用 AI Station 自動生成這支影片。"}'

# 查詢作業
curl http://localhost:8000/api/jobs
curl http://localhost:8000/api/jobs/<job_id>
```

### n8n 排程 / 自動化

`n8n/workflow.json` 是一個可直接匯入的範例流程：

1. **Schedule Trigger** — 每天 09:00 觸發（cron 可改）
2. **HTTP Request** — POST 到 `…/webhook/n8n`，body 帶 `title` + `script`
3. **IF** — 依 `status` 分支
4. **Discord / Slack / Telegram** — 成功傳影片網址，失敗傳錯誤

在 n8n 中：`Workflows → 匯入 from File` 選 `n8n/workflow.json`，把
`http://<AI_STATION_HOST>:8000` 改成你部署的位置（Docker / VPS）即可。
AI Station 也可用 Docker 跑在自有 VPS 上，完全對應 IDEA.md「n8n 部署於 VPS」。

## Runway 動態 B-roll (模組 4 雲端啟用)

填入 `RUNWAY_API_KEY` 後，每個鏡頭會改由 Runway 文字生影片產生 AI B-roll
片段（不再是靜態漸層圖）。未填則自動回落免費漸層背景。B-roll 模式會走
`visuals.generate_broll()`（非同步輪詢 Runway task），失敗同樣回落漸層。
> 註：Runway API 端點/輪詢格式依其現行版本調整；本專案提供 best-effort 接線。

## Docker Hub 自動發佈 (CI)

CI（`.github/workflows/build.yml`）在 push/PR 時建置映像：
- 未設 Docker Hub secrets → 只 build + load 驗證映像可建。
- 設了 `DOCKERHUB_USERNAME` + `DOCKERHUB_TOKEN`（repo **Settings → Secrets**）→
  自動 `docker push <user>/aistation:latest`。

```bash
# 在你自己的機器上跑（有正常 Docker 引擎）：
docker build -t <user>/aistation:latest .
docker push <user>/aistation:latest
```

## 目錄結構

```
aistation/
├── run.py              # 啟動入口
├── requirements.txt
├── Dockerfile          # 含 ffmpeg 的映像
├── docker-compose.yml
├── .env.example        # 所有可選雲端設定
├── n8n/workflow.json   # n8n 排程/Webhook 範例流程
├── .github/workflows/build.yml   # 建置 / 推 Docker Hub
├── src/
│   ├── app.py          # FastAPI 控制中心 (含 /webhook/n8n)
│   ├── config.py       # 設定 + 可插拔功能旗標
│   ├── db.py           # 模組 7：作業/溯源日誌 (SQLite / NCBDB)
│   ├── parser.py       # 模組 2：腳本 -> 鏡頭 (免費 / OpenAI)
│   ├── tts.py          # 模組 3：語音合成 (edge-tts / ElevenLabs) + 逐字時間戳
│   ├── visuals.py      # 模組 4：漸層 / Runway B-roll
│   ├── renderer.py      # 模組 5：ffmpeg 組裝 + Ken-Burns + 同步字幕
│   ├── storage.py      # 模組 6：發布 (本機 / S3)
│   └── pipeline.py     # 模組 1：管線編排中樞
├── web/index.html      # 控制中心的儀表板 UI
└── examples/sample_script.txt
```

## 總作業流程圖

![AI Station 總作業流程圖](diagrams/workflow.excalidraw)

互動版（可編輯）：https://excalidraw.com/#json=IzMNS_pLld_LW0NAaDuol,vqiuPpDPBiXv1u7bm6MwLg

涵蓋：Web 控制台 / n8n Webhook / REST API 三個入口 → 模組1 中樞 → 模組2~7
（解析→語音→視覺→渲染→發布→溯源），每個雲端模組（ElevenLabs / Runway /
S3 / NCBDB）以虛線標註「設 key 啟用」→ 輸出 MP4 → Docker / CI / n8n 部署層。

### 壽司博士 Dr. Source 品牌預設（sushi_dr）

專案內建《創價未來｜壽司博士 Dr. Source AI 協作視頻頻道規劃書 v1.0》的品牌預設，
讓管線直接產出符合頻道憲法的影片：深藍/暖金/米白/綠 配色、片頭標板、以及
「場景→衝突→洞察→方法→反思」的腳本 DNA。

用 DNA 標記寫腳本，解析器會「一標記一鏡位」自動套用對應品牌配色：

```
【場景】一家公司花了一年寫完永續報告，老闆只看了十分鐘。
【衝突】報告完成了，公司卻沒有改變。
【洞察】因為 ESG 被當成交付物，而不是經營系統。
【方法】用 1.0、1.5、2.0 檢查公司目前的位置。
【反思】如果永續只讓報告更漂亮，卻沒減少任何人的苦，算永續嗎？
```

呼叫時帶 `brand_preset`：

```bash
curl -X POST localhost:8000/api/jobs \
  -H 'content-type: application/json' \
  -d '{"script":"...上述 DNA 腳本...","brand_preset":"sushi_dr"}'
```

- `GET /api/brand`：回傳品牌設定（名稱/標語/配色/憲法/AI 邊界）。
- `GET /api/series`：回傳十條系列產品線 + 六個首季母題（含壽司博士原創判斷）。
- n8n webhook 亦接受 `brand_preset` 欄位。
- 未標記的腳本退回一般免費解析器；設 `OPENAI_API_KEY` 則改走 GPT-4o 解析。

## 容器化部署 (Docker)

![AI Station 時序圖](diagrams/sequence.excalidraw)

互動版：https://excalidraw.com/#json=m3ON1UO6ogF4MHzxNSEIZ,iTNL61SSEk5SgBnEp7V-nA

說明：用戶或 n8n 經 Webhook 觸發 → Pipeline 中樞依序呼叫 模組群
（解析 / 語音 / 視覺 / 渲染）產出 clips → Storage 存檔、DB 記溯源 → 回傳影片網址。

## 容器化部署 (Docker)

```bash
# 建立映像（ffmpeg 已內建於映像中，渲染引擎需要它）
docker build -t aistation:latest .

# 啟動（掛載 ./storage 以持久化影片與 SQLite）
docker run -d --name aistation -p 8000:8000 -v ./storage:/app/storage aistation:latest

# 或一次到位（docker compose）
docker compose up -d
```

> 所有雲端設定（OpenAI / ElevenLabs / Runway / S3 / NCBDB）可在
> `docker-compose.yml` 的 `environment:` 區塊填入，或直接掛載 `.env`。
> 不填則維持免費本地引擎。

> 驗證狀態：
> - 應用程式（FastAPI + ffmpeg 管線）已透過本地 venv 端對端驗證可產出 MP4。
> - Docker 映像已透過 GitHub Actions（`.github/workflows/build.yml`）在 Ubuntu
>   runner 上**實際建置成功**（`docker build` 已通過 CI，run 30155502256）。
>   本機 Docker Desktop daemon 因 WSL2/Hyper-V 後端問題無法啟動，故本地
>   `docker build` 改由 CI 代為驗證；有正常 Docker 引擎的機器可直接 `docker build`。

## 運作流程 (一次生成)

1. **解析** 腳本切成 N 個鏡頭（每鏡頭含 旁白 / 畫面提示詞 / 字幕）。
2. **語音** 每個鏡頭用 TTS 產生 MP3。
3. **畫面** 每個鏡頭用 Pillow 產生漸層背景圖。
4. **渲染** ffmpeg 對每張背景做 Ken-Burns 縮放平移，配對語音長度，串接成片。
5. **發布** 輸出 MP4 到 `./storage`，回傳可播放網址。
6. **溯源** 每個階段狀態寫入 SQLite（或 NCBDB）。

> 全程 headless、本地免費算力即可完成，完全符合 IDEA.md「筆電只負責規劃與監控」的架構。
