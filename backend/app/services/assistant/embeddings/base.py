"""Embedding provider abstract base.

Mirrors the LLMProvider pattern in
`app/services/assistant/providers/base.py` so every provider plugs in
the same way, the registry resolves them the same way, and admins
configure them via the same flow.

Why a separate provider abstraction from chat LLMs (instead of folding
embeddings into LLMProvider): embeddings have a fundamentally different
contract (text → vector, NOT text → text), separate pricing, separate
rate limits, and often a separate model selection even within the same
vendor (e.g., OpenAI's chat models are gpt-4o-mini etc., but embeddings
are text-embedding-3-small). Same auth credential is OK — but a clean
interface makes future swaps (e.g., Cohere embeddings + OpenAI chat)
trivial.
"""
from abc import ABC, abstractmethod
from typing import Iterable


class EmbeddingProvider(ABC):
    """One embedding model behind a uniform interface.

    Implementations must be safe to share across threads — the
    registry caches a single instance per active provider id.
    """
    name: str = "base"
    model: str = ""
    # Vector dimension this provider emits. Stored on each chunk so
    # retrieval can verify compatibility before computing distance.
    dimensions: int = 0

    @abstractmethod
    def embed_one(self, text: str) -> list[float]:
        """Embed a single piece of text. Returns a vector of length
        `self.dimensions`. Trim whitespace + reject empty text BEFORE
        calling — providers vary on their handling of empty input."""

    @abstractmethod
    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed many texts in a single API call. Order preserved.
        Implementations should batch at the provider's optimal size
        and concatenate transparently."""
