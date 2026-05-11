"""Embedding provider registry — mirrors LLMRegistry shape.

Resolves the active embedding provider by reading `embeddings.provider_id`
from settings_store, then loading the row from `llm_providers` (we
re-use that table — same vendor credentials, same auth flow).

Returned provider is cached with the same TTL knob (`embeddings.cache_ttl_seconds`).

Why re-use llm_providers instead of a new embedding_providers table:
the credential is the same (one OpenAI key serves both chat and embed),
the admin already configures it once, and adding a parallel table would
double the admin's setup work for zero functional gain. The provider
TYPE row identifies which capabilities apply — for now we just trust
that any 'openai' row can do both.
"""
import time
from threading import Lock
from app.core.database import SessionLocal
from app.core.settings_store import settings_store
from app.core.crypto import crypto
from app.models.llm_provider import LLMProviderConfig
from app.services.assistant.embeddings.base import EmbeddingProvider


def _provider_classes() -> dict[str, type[EmbeddingProvider]]:
    """Lazy-import so a missing optional vendor SDK doesn't kill module load."""
    out: dict[str, type[EmbeddingProvider]] = {}
    try:
        from app.services.assistant.embeddings.openai_provider import (
            OpenAIEmbeddingProvider,
        )
        out["openai"] = OpenAIEmbeddingProvider
    except Exception:                                       # pragma: no cover
        pass
    return out


class _CacheEntry:
    __slots__ = ("provider", "expires_at")

    def __init__(self, provider, expires_at):
        self.provider = provider
        self.expires_at = expires_at


class EmbeddingRegistry:
    _cache: dict[int, _CacheEntry] = {}
    _lock = Lock()

    @classmethod
    def get_active(cls) -> EmbeddingProvider:
        """Resolve the active embedding provider.

        Raises RuntimeError if no provider is configured or activation
        is pointed at an incompatible row. We do NOT silently fall back
        to a stub — embeddings without a real model produce garbage
        vectors that corrupt the rag_chunks corpus.
        """
        active_id = settings_store.get("embeddings.provider_id")
        if active_id is None:
            raise RuntimeError(
                "Embeddings not configured. Set `embeddings.provider_id` "
                "in admin → Runtime Settings to the id of an OpenAI "
                "LLMProviderConfig row.")
        return cls._get(int(active_id))

    @classmethod
    def invalidate(cls, provider_id: int | None = None) -> None:
        with cls._lock:
            if provider_id is None:
                cls._cache.clear()
            else:
                cls._cache.pop(provider_id, None)

    @classmethod
    def _get(cls, provider_id: int) -> EmbeddingProvider:
        ttl = settings_store.get_int("embeddings.cache_ttl_seconds", 60)
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
                raise RuntimeError(
                    f"Provider type '{row.provider_type}' has no embedding "
                    f"implementation. Pick an openai-typed row instead.")
            api_key = (
                crypto.decrypt(row.api_key_encrypted)
                if row.api_key_encrypted and crypto else None
            )
            # Optional model override — admins can store a specific
            # embedding model name on the LLMProviderConfig.config blob
            # (e.g. {"embedding_model": "text-embedding-3-large"}).
            model_override = (row.config or {}).get("embedding_model")
            provider = cls_(
                api_key=api_key, model=model_override,
                base_url=row.base_url,
            )

        with cls._lock:
            cls._cache[provider_id] = _CacheEntry(provider, now + ttl)
        return provider
