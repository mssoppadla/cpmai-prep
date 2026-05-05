from typing import Literal
from pydantic import BaseModel


ProviderType = Literal["openai", "anthropic", "azure_openai", "ollama", "stub"]


class LLMProviderCreate(BaseModel):
    name: str
    provider_type: ProviderType
    model: str
    api_key: str | None = None
    base_url: str | None = None
    config: dict | None = None
    is_enabled: bool = True
    priority: int = 100


class LLMProviderUpdate(BaseModel):
    name: str | None = None
    model: str | None = None
    api_key: str | None = None
    base_url: str | None = None
    config: dict | None = None
    is_enabled: bool | None = None
    priority: int | None = None


class LLMProviderOut(BaseModel):
    id: int
    name: str
    provider_type: str
    model: str
    base_url: str | None
    config: dict
    is_enabled: bool
    priority: int
    is_active: bool = False
    has_api_key: bool

    @classmethod
    def from_row(cls, row, is_active: bool = False):
        return cls(
            id=row.id, name=row.name, provider_type=row.provider_type,
            model=row.model, base_url=row.base_url, config=row.config or {},
            is_enabled=row.is_enabled, priority=row.priority,
            is_active=is_active, has_api_key=row.api_key_encrypted is not None,
        )
