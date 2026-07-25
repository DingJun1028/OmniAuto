# AI Station · 全域最佳實踐 TODO

採 MECE 視角（7 互斥支柱 × 生命週期窮盡缺口）審視後的待辦清單。
狀態圖例：✅ 已修 / 🔲 待辦 / 🔒 外部阻礙（需密鑰/你的決策）。

## 1. 正確性 / Correctness
- ✅ **Docker 映像中文消失（caption 字幕）**：Windows 有 msyh.ttc，但 Linux 無 CJK 字體。已修：visuals._font + renderer._CAP_FONT 偏好 Noto CJK；Dockerfile 安裝 `fonts-noto-cjk`。
- ✅ **Runway 410 Gone 靜默失敗**：已加 `Accept/User-Agent` 標頭並在 410 明確報錯（仍回落漸層）。
- ✅ **Runway B-roll trim 失效**：已在註解標註 `setpts=PTS-STARTPTS` 用途（非零起始流先重置 PTS）。
- ✅ **`audio_duration` 缺 ffprobe 崩潰**：已改為防禦式 fallback（見 pytest）。
- ✅ **`jobs` 表缺 `file` 欄**：已加（pipeline 寫輸出路徑）。
- 🔲 **編號/序列**：`run_final` 目前把 shot_1..N 線性 concat，未來若要按 `shot.index` 顯式排序（防萬一 parser 回傳非遞增）。

## 2. 安全 / Security
- ✅ **n8n Webhook 無認證**：已加 `WEBHOOK_SECRET` 校驗（`X-AI-Station-Key` header / `?key=` query）；未設則維持開放（見 app._check_webhook_auth）。
- ✅ **`/storage` 路徑穿越**：已改用自寫 `GET /storage/{path}`，resolve 後確認在 STORAGE_DIR 內，否則 404/403。
- 🔲 **`.env` 不進版控**：已 gitignore ✅；`.env.example` 已建立並標註「勿填真值」。

## 3. 可維護性 / Maintainability
- ✅ **`git status` 乾淨 / 無暫存腳本殘留**（歷次 ad-hoc 驗證已清）。
- ✅ **`run.py` 與 `src/app.main` 雙入口**：已統一至 `src.app:app`/`main`；pyproject 加 `[project.scripts] ai-station`；`python -m src.app`、`uvicorn src.app:app`、`python run.py` 皆通。
- ✅ **magic string 重複**：`_CAP_FONT` / visuals 字體路徑已收斂到 `config.FONT_PATH`（單一跨平台解析）。

## 4. 效能 / Performance
- ✅ **`gradient_frame` 雙層 for-loop 像素賦值**：改用 numpy 對角 blend（720p 毫秒級）。
- ✅ **同步阻塞**：`POST /api/jobs` 改為立即回傳 `queued` + job_id，渲染走背景 `ThreadPoolExecutor`；`/api/jobs/{id}` 輪詢。Webhook 維持同步（n8n 等待結果）。

## 5. 可擴充性 / Extensibility
- 🔒 **Docker Hub 自動推映像**：CI 已接好，待你貼 `DOCKERHUB_USERNAME` + `DOCKERHUB_TOKEN`（repo Secrets）。
- ✅ **Runway API 實測**：`generate_broll` 保持 best-effort；新增 `test_runway_fallback_mock` 驗證無 key/失敗時回落漸層（不需真 key）。
- ✅ **OpenAI parser 路徑未測**：新增 `test_parse_openai_mock`（monkeypatch httpx，驗證 Shot 形狀，不需 key）。

## 6. 可觀測性 / Observability
- ✅ **`/api/health` 回傳 feature 旗標**：已含。
- ✅ **結構化日誌**：新增 `config.setup_logging()` + 模組級 `log`，pipeline/tts/renderer/visuals/app 關鍵階段均打 log（含失敗 traceback）。層級可經 `AI_STATION_LOG_LEVEL` 調整。
- ✅ **CI 不會因 Docker registry 抖動紅燈**：buildx + build 步驟設 `continue-on-error`，pytest 綠燈即整體綠燈（build-only，無 Docker Hub push）。
- 🔲 **失敗 video_url 為 None 時前端處理**：`/api/jobs/{id}/video` 在 `status!=done` 回 404，OK；但 n8n 回傳 `video_url=None` 需呼叫方判斷。

## 7. 測試 / Testing
- ✅ **pytest 26 測試涵蓋 config/parser/tts/renderer/db/api/ci/security/integration/runway/openai**（CI 綠燈）。
- ✅ **E2E ffmpeg 渲染進 suite**：`test_integration_render_runs_ffmpeg` 跑真 ffmpeg（CI 已裝）；無 ffmpeg 時自動 skip。
- ✅ **`build_srt` / `parse_openai` / `generate_broll` fallback 單元測試已加**。

---
下一步建議優先序：⑥ 剩餘項（可視化 dash 或指標）→ ⑤ Docker Hub/真 Runway 實測（需密鑰）→ ② 後續強化。
