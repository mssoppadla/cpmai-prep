"""Dynamic LLM provider registry.

Loads providers from DB, decrypts keys, caches instances with TTL.
"""
import time
from threading import Lock
from app.core.database import SessionLocal
from app.core.settings_store import settings_store
from app.core.crypto import crypto
from app.models.llm_provider import LLMProviderConfig
from app.services.assistant.providers.base import LLMProvider
from app.services.assistant.providers.stub_provider import StubProvider


def _provider_classes():
    """Lazy-import provider classes so missing optional deps don't break imports."""
    out: dict[str, type[LLMProvider]] = {"stub": StubProvider}
    try:
        from app.services.assistant.providers.openai_provider import OpenAIProvider
        out["openai"] = OpenAIProvider
    except Exception:
        pass
    try:
        from app.services.assistant.providers.anthropic_provider import AnthropicProvider
        out["anthropic"] = AnthropicProvider
    except Exception:
        pass
    return out


class _CacheEntry:
    __slots__ = ("provider", "expires_at")

    def __init__(self, provider, expires_at):
        self.provider = provider
        self.expires_at = expires_at


class LLMRegistry:
    _cache: dict[int, _CacheEntry] = {}
    _lock = Lock()

    @classmethod
    def get_active(cls) -> LLMProvider:
        active_id = settings_store.get("llm.active_provider_id")
        if active_id is None:
            return StubProvider()
        try:
            return cls._get(int(active_id))
        except Exception:
            return cls._fallback()

    @classmethod
    def get_by_id(cls, provider_id: int) -> LLMProvider:
        return cls._get(provider_id)

    @classmethod
    def invalidate(cls, provider_id: int | None = None):
        with cls._lock:
            if provider_id is None:
                cls._cache.clear()
            else:
                cls._cache.pop(provider_id, None)

    @classmethod
    def _get(cls, provider_id: int) -> LLMProvider:
        ttl = settings_store.get_int("llm.cache_ttl_seconds", 30)
        now = time.monotonic()
        with cls._lock:
            entry = cls._cache.get(provider_id)
            if entry and entry.expires_at > now:
                return entry.provider

        with SessionLocal() as db:
            row = db.get(LLMProviderConfig, provider_id)
            if not row or not row.is_enabled:
                raise RuntimeError(f"Provider {provider_id} not available")
            classes = _provider_classes()
            cls_ = classes.get(row.provider_type)
            if not cls_:
                raise RuntimeError(f"Unknown provider_type: {row.provider_type}")
            api_key = (
                crypto.decrypt(row.api_key_encrypted)
                if row.api_key_encrypted and crypto else None
            )
            provider = cls_(
                model=row.model, api_key=api_key,
                base_url=row.base_url, **(row.config or {}),
            )

        with cls._lock:
            cls._cache[provider_id] = _CacheEntry(provider, now + ttl)
        return provider

    @classmethod
    def _fallback(cls) -> LLMProvider:
        fid = settings_store.get("llm.fallback_provider_id")
        if fid:
            try:
                return cls._get(int(fid))
            except Exception:
                pass
        return StubProvider()
