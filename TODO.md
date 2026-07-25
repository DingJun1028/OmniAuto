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
- 🔲 **n8n Webhook 無認證**：任何人可 POST `/webhook/n8n` 觸發生成（算力耗盡風險）。建議加 shared token 校驗（`X-AI-Station-Key` header 或 query secret）。
- 🔲 **`/storage` 靜態掛載暴露所有影片**：建議加 path-traversal 防護或改走 signed URL。
- 🔲 **`.env` 不進版控**：已 gitignore ✅；但 `.env.example` 應標註「勿填真值」。

## 3. 可維護性 / Maintainability
- ✅ **`git status` 乾淨 / 無暫存腳本殘留**（歷次 ad-hoc 驗證已清）。
- 🔲 **`run.py` 與 `src/app.main` 雙入口**：建議統一至一處或加 `pyproject` 的 `[project.scripts]`。
- 🔲 **magic string 重複**：`_CAP_FONT` Windows 路徑在 visuals/render 各寫一次；建議收斂到 `config.FONT_PATH`。

## 4. 效能 / Performance
- 🔲 **`gradient_frame` 雙層 for-loop 像素賦值**（720p ~92 萬次迭代）：可用 `Image.linear_gradient` 或 numpy 向量化；免費模式每次生成都重畫。
- 🔲 **同步阻塞**：`pipeline.enqueue` 在 request 線程跑完整 ffmpeg（數十秒）。建議改 background task + `/api/jobs` 輪詢（Webhook 已同步回傳，但長腳本會 timeout）。

## 5. 可擴充性 / Extensibility
- 🔒 **Docker Hub 自動推映像**：CI 已接好，待你貼 `DOCKERHUB_USERNAME` + `DOCKERHUB_TOKEN`（repo Secrets）。
- 🔲 **Runway API 實測**：目前 best-effort，無 key 無法驗證；建議在 README 註明「需你實測調整 endpoint」。
- 🔲 **OpenAI parser 路徑未測**：`parse_openai` 無單元測（需 key）；建議加 mock 測試。

## 6. 可觀測性 / Observability
- ✅ **`/api/health` 回傳 feature 旗標**：已含。
- 🔲 **結構化日誌**：目前無 logging，僅 DB 狀態；建議加 `logging` 到 pipeline 各階段。
- 🔲 **失敗 video_url 為 None 時前端處理**：`/api/jobs/{id}/video` 在 `status!=done` 回 404，OK；但 n8n 回傳 `video_url=None` 需呼叫方判斷。

## 7. 測試 / Testing
- ✅ **pytest 16 測試涵蓋 config/parser/tts/renderer/db/api/ci**（CI 綠燈）。
- 🔲 **E2E ffmpeg 渲染未進 suite**：目前靠 CI 建置 + ad-hoc 腳本；建議加一個 `pytest --integration` 標記跑真 ffmpeg（CI 已裝 ffmpeg）。
- 🔲 **`build_srt` 單元測試已加** ✅；`generate_broll` 建議加 mock httpx 測。

---
下一步建議優先序：② 安全（webhook 認證）→ ④ 效能（gradient 向量化 + 背景任務）→ ⑦ E2E 測試標記。
