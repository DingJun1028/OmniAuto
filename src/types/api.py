"""Pydantic 模型 — AI Station API 的單一事實來源。

所有前端 TypeScript 型別（web/src/types/api.ts）與 Zod schema（schemas.ts）
皆從此處同步，確保全端型別一致性。
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class ScriptIn(BaseModel):
    """POST /api/jobs 請求體。"""
    title: str = Field(default="", description="影片標題")
    script: str = Field(..., description="腳本內容（支援 DNA 標記）")
    brand_preset: str = Field(default="sushi_dr", description="品牌預設名稱")


class WebhookIn(BaseModel):
    """POST /webhook/n8n 請求體（n8n 自動化 webhook）。"""
    title: str = Field(default="", alias="title")
    script: Optional[str] = Field(default=None, alias="script")
    text: Optional[str] = Field(default=None, alias="text")
    brand_preset: str = Field(default="sushi_dr", description="品牌預設名稱")

    @property
    def body(self) -> str:
        return self.script or self.text or ""


class JobResponse(BaseModel):
    """GET /api/jobs/{id} 回應 — 作業狀態與結果。"""
    job_id: str
    title: str = ""
    status: str = "queued"
    progress: int = 0
    created_at: str = ""
    updated_at: str = ""
    payload: Any = None
    result: Any = None
