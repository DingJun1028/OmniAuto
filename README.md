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

# 查詢作業
curl http://localhost:8000/api/jobs
curl http://localhost:8000/api/jobs/<job_id>
```

## 目錄結構

```
aistation/
├── run.py              # 啟動入口
├── requirements.txt
├── .env.example        # 所有可選雲端設定
├── src/
│   ├── app.py          # FastAPI 控制中心的 HTTP 層
│   ├── config.py       # 設定 + 可插拔功能旗標
│   ├── db.py           # 模組 7：作業/溯源日誌 (SQLite / NCBDB)
│   ├── parser.py       # 模組 2：腳本 -> 鏡頭 (免費 / OpenAI)
│   ├── tts.py          # 模組 3：語音合成 (edge-tts / ElevenLabs)
│   ├── visuals.py      # 模組 4：畫面生成 (Pillow / Runway)
│   ├── renderer.py     # 模組 5：ffmpeg 組裝 + Ken-Burns
│   ├── storage.py      # 模組 6：發布 (本機 / S3)
│   └── pipeline.py     # 模組 1：管線編排中樞
├── web/index.html      # 控制中心的儀表板 UI
└── examples/sample_script.txt
```

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
