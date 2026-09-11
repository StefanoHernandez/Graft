"""Request and response shapes for the admin API.

Input and output are separate types on purpose: an API key goes in and must
never come back out. Responses carry `has_api_key`, never the key itself.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class Page[T](BaseModel):
    items: list[T]
    total: int


class ProviderConfigIn(BaseModel):
    provider: str
    model: str
    base_url: str | None = None
    api_key: str | None = None


class ProviderConfigOut(BaseModel):
    provider: str
    model: str
    base_url: str | None = None
    has_api_key: bool

    @classmethod
    def from_stored(cls, config: dict | None) -> ProviderConfigOut | None:
        if not config:
            return None
        return cls(
            provider=config.get("provider", ""),
            model=config.get("model", ""),
            base_url=config.get("base_url"),
            has_api_key=bool(config.get("api_key")),
        )


class BotCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    allowed_origins: list[str] = []
    llm_config: ProviderConfigIn | None = None
    embedding_config: ProviderConfigIn | None = None
    system_prompt: str = ""
    theme: dict = {}
    retrieval_config: dict = {}


class BotUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    allowed_origins: list[str] | None = None
    llm_config: ProviderConfigIn | None = None
    embedding_config: ProviderConfigIn | None = None
    system_prompt: str | None = None
    theme: dict | None = None
    retrieval_config: dict | None = None


class BotOut(BaseModel):
    id: uuid.UUID
    name: str
    widget_key: str
    allowed_origins: list[str]
    llm_config: ProviderConfigOut | None
    embedding_config: ProviderConfigOut | None
    system_prompt: str
    theme: dict
    retrieval_config: dict
    created_at: datetime


class DocumentOut(BaseModel):
    id: uuid.UUID
    filename: str
    mime_type: str
    status: str
    error: str | None
    chunk_count: int
    created_at: datetime
    updated_at: datetime


class ProviderCheck(BaseModel):
    ok: bool
    code: str | None = None


class ProviderTestOut(BaseModel):
    llm: ProviderCheck
    embedding: ProviderCheck


class ConversationOut(BaseModel):
    id: uuid.UUID
    # A short label, never the session id itself: that id is the visitor's
    # capability to resume their conversation on the public endpoint.
    label: str
    started_at: datetime
    message_count: int
    last_activity_at: datetime | None


class MessageOut(BaseModel):
    id: uuid.UUID
    role: str
    content: str
    status: str
    citations: list[dict]
    created_at: datetime


class ConversationDetail(BaseModel):
    id: uuid.UUID
    label: str
    started_at: datetime
    messages: list[MessageOut]
