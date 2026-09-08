from __future__ import annotations

from pydantic import BaseModel


class LLMConfig(BaseModel):
    provider: str
    model: str
    base_url: str | None = None
    api_key: str | None = None
    api_key_encrypted: bool = True


class EmbeddingConfig(BaseModel):
    provider: str
    model: str
    base_url: str | None = None
    api_key: str | None = None
    api_key_encrypted: bool = True
