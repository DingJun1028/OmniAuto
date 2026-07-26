# AI Station · 全域最佳實踐 TODO

採 MECE 視角（7 互斥支柱 × 生命週期窮盡缺口）審視後的待辦清單。
狀態圖例：✅ 已修 / 🔲 待辦 / 🔒 外部阻礙（需密鑰/你的決策）。

## 1. 正確性 / Correctness
- ✅ **Docker 映像中文消失（caption 字幕）**：Windows 有 msyh.ttc，但 Linux 無 CJK 字體。已修：visuals._font + renderer._CAP_FONT 偏好 Noto CJK；Dockerfile 安裝 `fonts-noto-cjk`。
- ✅ **Runway 410 Gone 靜默失敗**：已加 `Accept/User-Agent` 標頭並在 410 明確報錯（仍回落漸層）。
- ✅ **Runway B-roll trim 失效**：已在註解標註 `setpts=PTS-STARTPTS` 用途（非零起始流先重置 PTS）。
- ✅ **`audio_duration` 缺 ffprobe 崩潰**：已改為防禦式 fallback（見 pytest）。
- ✅ **`jobs` 表缺 `file` 欄**：已加（pipeline 寫輸出路徑）。
- ✅ **背景 job 靜默卡死（嚴重 bug）**：`pipeline.submit` 把 `run_pipeline` 丟進 ThreadPoolExecutor 卻無例外處理，渲染失敗時 job 永遠卡在 `queued`/`rendering`。已修：submit 內包 `_run()` try/except，失敗寫 `failed` + log.exception；新增 `test_submit_marks_failed_on_render_error` 回歸。
- 🔲 **編號/序列**：`run_final` 目前把 shot_1..N 線性 concat，未來若要按 `shot.index` 顯式排序（防萬一 parser 回傳非遞增）。
- ✅ **編號/序列防禦**：`run_pipeline` 在建 clips 後改以每 shot 的 `index` 顯式排序再 concat（`render_final` 的 `shots` 參數現為排序後的 shot dicts，長度不符會打 warning）；parser 回傳非遞增 index 也不再影響播放順序。

## 2. 安全 / Security
- ✅ **n8n Webhook 無認證**：已加 `WEBHOOK_SECRET` 校驗（`X-AI-Station-Key` header / `?key=` query）；未設則維持開放（見 app._check_webhook_auth）。
- ✅ **Webhook 金鑰定時側信道**：比較改用 `hmac.compare_digest`（常數時間），不再用 `!=`。
- ✅ **`/storage` 路徑穿越**：已改用自寫 `GET /storage/{path}`，resolve 後確認在 STORAGE_DIR 內，否則 404/403。
- ✅ **`.env` 不進版控**：已 gitignore（`.gitignore` 含 `.env`）；`.env.example` 已建立並標註「勿填真值」。

## 3. 可維護性 / Maintainability
- ✅ **`git status` 乾淨 / 無暫存腳本殘留**（歷次 ad-hoc 驗證已清）。
- ✅ **`run.py` 與 `src/app.main` 雙入口**：已統一至 `src.app:app`/`main`；pyproject 加 `[project.scripts] ai-station`；`python -m src.app`、`uvicorn src.app:app`、`python run.py` 皆通。
- ✅ **magic string 重複**：`_CAP_FONT` / visuals 字體路徑已收斂到 `config.FONT_PATH`（單一跨平台解析）。
- ✅ **執行緒池優雅關閉**：`pipeline._pool` 加 `atexit` 關閉（reload/test 不漏 thread）。

## 4. 效能 / Performance
- ✅ **`gradient_frame` 雙層 for-loop 像素賦值**：改用 numpy 對角 blend（720p 毫秒級）。
- ✅ **同步阻塞**：`POST /api/jobs` 改為立即回傳 `queued` + job_id，渲染走背景 `ThreadPoolExecutor`；`/api/jobs/{id}` 輪詢。Webhook 維持同步（n8n 等待結果）。

## 5. 可擴充性 / Extensibility
- 🔒 **Docker Hub 自動推映像**：CI 已接好，待你貼 `DOCKERHUB_USERNAME` + `DOCKERHUB_TOKEN`（repo Secrets）。
- ✅ **Runway API 實測**：`generate_broll` 保持 best-effort；新增 `test_runway_fallback_mock` 驗證無 key/失敗時回落漸層（不需真 key）。
- ✅ **OpenAI parser 路徑未測**：新增 `test_parse_openai_mock`（monkeypatch httpx，驗證 Shot 形狀，不需 key）。
- ✅ **S3 上傳可靠性**：`storage.upload_s3` 加 `ContentType=video/mp4` + `TransferConfig`（並發/分段）；`boto3` 列入 pyproject `[project.optional-dependencies].s3`（免費路徑不受影響）。

## 6. 可觀測性 / Observability
- ✅ **`/api/health` 回傳 feature 旗標**：已含。
- ✅ **結構化日誌**：新增 `config.setup_logging()` + 模組級 `log`，pipeline/tts/renderer/visuals/app 關鍵階段均打 log（含失敗 traceback）。層級可經 `AI_STATION_LOG_LEVEL` 調整。
- ✅ **CI 不會因 Docker registry 抖動紅燈**：buildx + build 步驟設 `continue-on-error`，pytest 綠燈即整體綠燈（build-only，無 Docker Hub push）。
- ✅ **失敗 video_url 為 None 時處理**：webhook 回傳新增 `ok` 旗標（`status==done` 且有 `video_url` 才 True），`video_url=None` 時 `ok=False` 且 `error` 回填；n8n 呼叫方可直接 `if (body.ok)` 分支，不再依賴 None 判斷。新增 `test_webhook_ok_flag_reflects_video` 回歸。

## 7. 測試 / Testing
- ✅ **pytest 28 測試涵蓋 config/parser/tts/renderer/db/api/ci/security/integration/runway/openai/webhook**（CI 綠燈）。
- ✅ **E2E ffmpeg 渲染進 suite**：`test_integration_render_runs_ffmpeg` 跑真 ffmpeg（CI 已裝）；無 ffmpeg 時自動 skip。
- ✅ **測試不污染真實狀態**：render 類測試加 `isolated_state` fixture，把 `jobs.db` + `STORAGE_DIR` 導向 tmp（不再寫入 repo 根目錄）。
- ✅ **`build_srt` / `parse_openai` / `generate_broll` fallback / submit 失敗 單元測試已加**。

---
下一步建議優先序：⑤ Docker Hub 自動推映像（待你貼 `DOCKERHUB_USERNAME`+`DOCKERHUB_TOKEN`）/ 真 Runway 實測（需密鑰）→ ⑥ 可視化 dash 或指標（可選增強）。其餘 ①/②/③ 已修。
