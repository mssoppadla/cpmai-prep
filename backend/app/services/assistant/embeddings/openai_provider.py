"""OpenAI embeddings provider.

Reuses the API key stored on an `LLMProviderConfig` row (provider_type
== 'openai'). Why share the credential instead of adding a separate
`embedding_providers` table: same OpenAI account, same key, embeddings
are just another endpoint on the same vendor — admins configuring
"my OpenAI key" once should not have to repeat it for chat AND embed.
If a future operator wants to use a totally different vendor for
embeddings (e.g., Cohere), they add a row + select it — that's clean.

Cost note: text-embedding-3-small is ~$0.02 per 1M tokens. Our entire
corpus (FAQ + Plans + ~150 question explanations) is well under 200K
tokens, so a full re-embed is ~$0.004. Incremental on-change embeds
are noise.
"""
from app.services.assistant.embeddings.base import EmbeddingProvider


class OpenAIEmbeddingProvider(EmbeddingProvider):
    name = "openai"
    # text-embedding-3-small chosen over -large for cost/quality balance.
    # 1536 dims; matches the vector column type in migration 0009.
    model = "text-embedding-3-small"
    dimensions = 1536

    # Provider's max input per request — we chunk caller batches to stay
    # under this. 2048 is conservative (actual limit is higher but
    # depends on token count, not item count).
    _BATCH_SIZE = 256

    def __init__(self, api_key: str, model: str | None = None,
                 base_url: str | None = None):
        # Lazy-import OpenAI SDK so missing optional dep doesn't break
        # module load — mirrors the chat provider pattern.
        try:
            from openai import OpenAI
        except ImportError as e:                            # pragma: no cover
            raise RuntimeError(
                f"OpenAI SDK failed to load: {type(e).__name__}: {e}. "
                "Rebuild the backend image; check requirements.txt has openai."
            ) from e
        self._client = OpenAI(api_key=api_key, base_url=base_url or None)
        if model:
            self.model = model

    def embed_one(self, text: str) -> list[float]:
        if not text or not text.strip():
            raise ValueError("Cannot embed empty text")
        return self.embed_batch([text])[0]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        # Defensive: strip + drop empties (caller should have, but the
        # API will hard-fail on a blank string in the batch).
        cleaned = [t.strip() for t in texts if t and t.strip()]
        if len(cleaned) != len(texts):
            raise ValueError(
                "embed_batch received empty/whitespace text — caller "
                "must filter before invoking.")

        out: list[list[float]] = []
        for start in range(0, len(cleaned), self._BATCH_SIZE):
            batch = cleaned[start:start + self._BATCH_SIZE]
            resp = self._client.embeddings.create(
                model=self.model,
                input=batch,
                # Explicit dimensions to fail-loud if anyone swaps to a
                # model with a different default.
                dimensions=self.dimensions,
            )
            out.extend(d.embedding for d in resp.data)
        return out
