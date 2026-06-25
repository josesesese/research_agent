"""Embedding providers for RAG."""

from __future__ import annotations

import hashlib
import math
import os
import re
from typing import Protocol

from research_agent.gemini_client import GeminiAPIError, GeminiClient
from research_agent.openai_client import OpenAIAPIError, OpenAIClient


class EmbeddingProvider(Protocol):
    name: str

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts."""


class HashEmbeddingProvider:
    """Deterministic local embeddings for zero-cost demos and tests."""

    name = "hash"

    def __init__(self, dimensions: int = 128) -> None:
        self.dimensions = dimensions

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def _embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        tokens = re.findall(r"[\w\u4e00-\u9fff]+", text.lower())
        for token in tokens:
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            bucket = int.from_bytes(digest[:4], "big") % self.dimensions
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[bucket] += sign
        return normalize(vector)


class OpenAIEmbeddingProvider:
    """OpenAI embeddings backed by the Embeddings API."""

    name = "openai"

    def __init__(
        self,
        client: OpenAIClient | None = None,
        model: str | None = None,
        dimensions: int | None = None,
    ) -> None:
        self.client = client or OpenAIClient()
        self.model = model or os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
        self.dimensions = dimensions

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        return self.client.create_embeddings(self.model, texts, dimensions=self.dimensions)


class GeminiEmbeddingProvider:
    """Gemini embeddings backed by the Gemini API."""

    name = "gemini"

    def __init__(
        self,
        client: GeminiClient | None = None,
        model: str | None = None,
        dimensions: int | None = None,
    ) -> None:
        self.client = client or GeminiClient()
        self.model = model or os.getenv("GEMINI_EMBEDDING_MODEL", "gemini-embedding-2")
        self.dimensions = dimensions or int(os.getenv("GEMINI_EMBEDDING_DIMENSIONS", "768"))

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        return self.client.create_embeddings(self.model, texts, dimensions=self.dimensions)


class AutoEmbeddingProvider:
    """Use Gemini embeddings when configured, otherwise local hash embeddings."""

    name = "auto"

    def __init__(self, gemini_provider: GeminiEmbeddingProvider | None = None) -> None:
        self.gemini_provider = gemini_provider or GeminiEmbeddingProvider()
        self.fallback_provider = HashEmbeddingProvider()
        self.last_used_provider = "unknown"
        self.last_error = ""

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if self.gemini_provider.client.is_configured:
            try:
                vectors = self.gemini_provider.embed_texts(texts)
                self.last_used_provider = "gemini"
                self.last_error = ""
                return vectors
            except GeminiAPIError as exc:
                self.last_error = exc.brief()
        self.last_used_provider = "hash"
        return self.fallback_provider.embed_texts(texts)


def build_embedding_provider(mode: str | None = None) -> EmbeddingProvider:
    selected = (mode or os.getenv("RESEARCH_AGENT_EMBEDDING_MODE", "gemini")).strip().lower()
    if selected == "hash":
        return HashEmbeddingProvider()
    if selected == "gemini":
        return GeminiEmbeddingProvider()
    if selected == "openai":
        return OpenAIEmbeddingProvider()
    if selected == "auto":
        return AutoEmbeddingProvider()
    raise ValueError("Embedding mode must be hash, gemini, openai, or auto.")


def normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    if not norm:
        return vector
    return [value / norm for value in vector]
