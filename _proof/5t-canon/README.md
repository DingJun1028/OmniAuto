# 5T-Canon 證明存證目錄

由 OA-Team 30 萬能蜂群 5T 驗證閘產出並凍結的格式證明存檔。

## 主證明（inclusionai/ling-3.0-flash-fin:free）

| 檔案 | 用途 |
|---|---|
| `5T_canon_proof_ling.json` | 主要證明文件（3,486 bytes） |
| `gen_5t_proof.py` | 證明生成器（呼叫 `gate5t.verify_5t` + `lock_artifact`） |
| `verify_5t_proof.py` | 證明完整性驗證（re-verification + immutability test） |
| `verify_hash.py` | Payload digest 對照 + hash 一致性說明 |

## 交叉驗證（inclusionai/ling-3.0-flash-fin:free vs ollama/gemma4-3b-it）

| 檔案 | 模型 | Hash Lock (前 20) |
|---|---|---|
| `5T_canon_proof_modelA.json` | `inclusionai/ling-3.0-flash-fin:free` | `07fb6b6335f369317fb0...` |
| `5T_canon_proof_modelB.json` | `ollama/gemma4-3b-it` | `6acbfd27fb924b553a1d...` |
| `gen_5t_cross_proof.py` | 雙模型獨立驗證腳本 | — |

## 驗證結果摘要

```
Model A (ling-3.0-flash-fin:free):  5T PASS  hash=07fb6b6335f369317fb0...
Model B (ollama/gemma4-3b-it):     5T PASS  hash=6acbfd27fb924b553a1d...
Both pass 5T gate: True
Hashes distinct (provenance differs): True
Immutability: FrozenInstanceError confirmed
```

## 重現步驟

```bash
cd C:\Project\aistation
.venv\Scripts\python.exe gen_5t_cross_proof.py
.venv\Scripts\python.exe verify_5t_proof.py
```

## 5T 驗證閘

| 支柱 | 內容 |
|---|---|
| Traceable | uuid + source_origin + sources + evidence_chain |
| Trackable | lifecycle_hooks + timestamp + iso_8601 + process_trace |
| Tangible | hash_lock + checks + kind + quality_gate |
| Transparent | version + transparent_audit + zero_hallucination + algorithm_open |
| Trustworthy | frozen + hash_lock (SHA-256) + @dataclass(frozen=True) |

## 系統版本

ESG GO v0.12 (InfoOne Core) · AGPL-3.0 · 熵減目標 < 0.1

## 不可篡改保證

所有證明文件皆透過 `gate5t.lock_artifact()` 凍結為 `@dataclass(frozen=True)`。
任何 mutate 操作都會觸發 `FrozenInstanceError`。
