"""Local JSON vector store and RAG helpers."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from research_agent.embeddings import EmbeddingProvider
from research_agent.models import Document, RetrievedChunk


@dataclass(frozen=True)
class TextChunk:
    id: str
    source_id: str
    title: str
    url: str
    text: str


class LocalVectorStore:
    """A small persistent vector database stored as JSON."""

    def __init__(self, path: Path | str = "vector_store/research_agent_vectors.json") -> None:
        self.path = Path(path)
        self.records: dict[str, dict[str, Any]] = {}
        self._load()

    def upsert_chunks(self, chunks: list[TextChunk], vectors: list[list[float]]) -> None:
        if len(chunks) != len(vectors):
            raise ValueError("Chunks and vectors must have the same length.")

        for chunk, vector in zip(chunks, vectors, strict=True):
            self.records[chunk.id] = {
                "id": chunk.id,
                "source_id": chunk.source_id,
                "title": chunk.title,
                "url": chunk.url,
                "text": chunk.text,
                "embedding": vector,
            }
        self._save()

    def search(
        self,
        query_vector: list[float],
        top_k: int = 5,
        source_ids: set[str] | None = None,
    ) -> list[RetrievedChunk]:
        scored: list[tuple[float, dict[str, Any]]] = []
        for record in self.records.values():
            if source_ids is not None and record["source_id"] not in source_ids:
                continue
            score = cosine_similarity(query_vector, record["embedding"])
            scored.append((score, record))

        scored.sort(key=lambda item: item[0], reverse=True)
        return [
            RetrievedChunk(
                id=record["id"],
                source_id=record["source_id"],
                text=record["text"],
                score=round(float(score), 4),
                rank=rank,
            )
            for rank, (score, record) in enumerate(scored[:top_k], start=1)
        ]

    def _load(self) -> None:
        if not self.path.exists():
            self.records = {}
            return
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        records = raw.get("records", [])
        self.records = {record["id"]: record for record in records if "id" in record}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "records": list(self.records.values()),
        }
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def build_chunks(
    documents: list[Document],
    chunk_size: int = 900,
    overlap: int = 120,
    max_chunks: int = 40,
) -> list[TextChunk]:
    chunks: list[TextChunk] = []
    for document in documents:
        text = " ".join(document.text.split())
        if not text:
            continue

        start = 0
        while start < len(text) and len(chunks) < max_chunks:
            end = min(start + chunk_size, len(text))
            chunk_text = text[start:end].strip()
            if chunk_text:
                chunk_id = stable_chunk_id(document.source.id, chunk_text)
                chunks.append(
                    TextChunk(
                        id=chunk_id,
                        source_id=document.source.id,
                        title=document.source.title,
                        url=document.source.url,
                        text=chunk_text,
                    )
                )
            if end == len(text):
                break
            start = max(end - overlap, start + 1)
    return chunks


def index_and_retrieve(
    question: str,
    documents: list[Document],
    embedding_provider: EmbeddingProvider,
    vector_store_path: Path | str,
    top_k: int = 5,
) -> tuple[list[RetrievedChunk], str]:
    chunks = build_chunks(documents)
    if not chunks:
        return [], getattr(embedding_provider, "name", "unknown")

    store = LocalVectorStore(vector_store_path)
    vectors = embedding_provider.embed_texts([chunk.text for chunk in chunks])
    store.upsert_chunks(chunks, vectors)

    query_vector = embedding_provider.embed_texts([question])[0]
    source_ids = {document.source.id for document in documents}
    retrieved = store.search(query_vector, top_k=top_k, source_ids=source_ids)
    provider_name = getattr(embedding_provider, "last_used_provider", getattr(embedding_provider, "name", "unknown"))
    return retrieved, provider_name


def stable_chunk_id(source_id: str, text: str) -> str:
    digest = hashlib.sha1(f"{source_id}:{text}".encode("utf-8")).hexdigest()[:16]
    return f"chunk_{digest}"


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if not left_norm or not right_norm:
        return 0.0
    return dot / (left_norm * right_norm)
