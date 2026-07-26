# 永久免費雲端部署（Oracle Always-Free ARM）

AI Station 的容器映像已發布為 **多架構（linux/amd64 + linux/arm64）**，
因此能原生跑在 Oracle Cloud 的 **Always-Free ARM64 執行個體**（4 OCPU / 24GB RAM，
永久免費、不需信用卡續費）上，不需要任何雲端運算費用。本檔說明從一臺全新的
免費機到 AI Station 上線的最小步驟。

---

## 1. 開一台 Always-Free ARM 機（一次性）

1. 到 https://cloud.oracle.com → 建立 **VM.Standard.A1.Flex**
   - Shape：4 OCPU / 24 GB RAM（免費額度上限）
   - Image：Ubuntu 22.04 / 24.04 LTS（ARM64）
   - 網路：勾選「指派公網 IP」；**Ingress Rules** 開放 `22/tcp`（SSH）、
     `80/tcp`、`443/tcp`（之後 certbot 用）。Oracle 預設安全清單（Security List）
     要手動加 80/443 的無狀態入口規則。
2. 記下公網 IP（例如 `161.118.252.147`）與預設使用者 `ubuntu`（或 `opc`，視 image）。

> 這臺機器就是「永久免費雲端」。esggo 現有的 `161.118.252.147` VPS 也是同一臺
> ARM 機；以下步驟對兩者通用。

---

## 2. 把本機公鑰加進 VPS（一次性，解鎖 SSH）

本機公鑰在 `~/.ssh/id_rsa_esggo.pub`。把內容貼到 VPS 的 `~/.ssh/authorized_keys`：

```bash
# 在本機：把公鑰 pipe 進 VPS（首次用密碼登入，或 Oracle 提供的 SSH key）
cat ~/.ssh/id_rsa_esggo.pub | ssh ubuntu@161.118.252.147 'mkdir -p ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys'
```

確認可免密登入：

```bash
ssh -i ~/.ssh/id_rsa_esggo ubuntu@161.118.252.147 'echo SSH-OK'
```

---

## 3. 一鍵部署（本機執行）

```bash
./deploy/deploy.sh ubuntu@161.118.252.147 aistation.esggo.co
```

`deploy.sh` 會（冪等、非破壞）：

0. **bootstrap**：若 VPS 還沒裝 docker / nginx，自動裝好（Oracle 免費 Ubuntu ARM64 適用），
   並啟用 `docker` + `nginx` 開機自啟。已裝則跳過。
1. 把 `deploy/`（compose + nginx + .env.example）rsync 到 `~/aistation/deploy`。
2. `docker compose pull && up -d`：拉取多架構映像，ARM 機上**原生跑 arm64**，
   不經 QEMU，渲染效能最好。`restart: unless-stopped` 確保重開機自動回復。
3. 啟用 nginx 反向代理（domain 走 `aistation.esggo.co.conf`）。
4. 健康檢查 `/api/health`。

---

## 4. 伺服器端 `.env`（金鑰選填，勿進 git）

```bash
ssh ubuntu@161.118.252.147 'cp ~/aistation/deploy/.env.example ~/aistation/deploy/.env'
# 然後 vim ~/aistation/deploy/.env 補填 WEBHOOK_SECRET / RUNWAY_API_KEY / ELEVENLABS_API_KEY
ssh ubuntu@161.118.252.147 'cd ~/aistation/deploy && docker compose up -d'   # 套用新環境變數
```

留白即走免費路徑（edge-tts + ffmpeg + Pillow），永久免費雲端仍能全功能產片。

---

## 5. DNS + HTTPS（Let's Encrypt，免費）

`aistation.esggo.co` 的 A/AAAA 指向 VPS IP；`www.esggo.co` 若走 Cloudflare 代理，
子域要設 **DNS-only（灰雲）** 或保留橙雲但 origin 指向同一 IP。然後：

```bash
ssh ubuntu@161.118.252.147 'sudo apt-get install -y certbot python3-certbot-nginx && sudo certbot --nginx -d aistation.esggo.co'
```

certbot 會自動改 nginx 加上 443 + HTTP→HTTPS 跳轉，並排定自動續期。

---

## 6. 維運

```bash
ssh ubuntu@161.118.252.147 'cd ~/aistation/deploy && docker compose pull && docker compose up -d'   # 升級到最新映像
ssh ubuntu@161.118.252.147 'cd ~/aistation/deploy && docker compose logs --tail=50'                  # 看日誌
ssh ubuntu@161.118.252.147 'cd ~/aistation/deploy && docker compose restart'                         # 重啟
```

映像更新由 CI 自動推（main push → 多架構 `docker.io/dingjunhong1028/aistation:latest`），
VPS 只需 `compose pull` 即可升級，全程免費。

---

## 費用總結

| 項目 | 費用 |
|------|------|
| Oracle Always-Free ARM64 VM | $0（永久免費） |
| Docker Hub 公開映像 | $0 |
| Let's Encrypt 憑證 | $0 |
| 預設渲染（edge-tts + ffmpeg + Pillow） | $0 |
| Runway / ElevenLabs（選用） | 僅當你填入金鑰才產生費用 |

→ AI Station 在永久免費雲端即可 7×24 全功能運作；只有想升級畫質/語音時才付雲端金鑰的錢。
