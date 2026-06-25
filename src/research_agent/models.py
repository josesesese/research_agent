"""Core data models for the research pipeline."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any


class SourceType(str, Enum):
    OFFICIAL = "official"
    DOCUMENTATION = "documentation"
    NEWS = "news"
    REVIEW = "review"
    COMMUNITY = "community"
    MOCK = "mock"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ResearchQuestion:
    text: str
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


@dataclass(frozen=True)
class ResearchSubQuestion:
    id: str
    text: str
    rationale: str


@dataclass(frozen=True)
class ResearchPlan:
    question: ResearchQuestion
    sub_questions: list[ResearchSubQuestion]
    search_queries: list[str]


@dataclass(frozen=True)
class Source:
    id: str
    title: str
    url: str
    source_type: SourceType
    published_at: str | None = None
    snippet: str = ""


@dataclass(frozen=True)
class Document:
    source: Source
    text: str
    fetched_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    read_error: str | None = None


@dataclass(frozen=True)
class Evidence:
    id: str
    source_id: str
    quote: str
    note: str
    confidence: float = 0.7


@dataclass(frozen=True)
class Claim:
    id: str
    topic: str
    text: str
    evidence_ids: list[str]
    confidence: float = 0.7


@dataclass(frozen=True)
class RetrievedChunk:
    id: str
    source_id: str
    text: str
    score: float
    rank: int


@dataclass(frozen=True)
class CitationIssue:
    claim_id: str
    message: str


@dataclass(frozen=True)
class CitationCheckResult:
    passed: bool
    issues: list[CitationIssue]


@dataclass(frozen=True)
class ResearchReport:
    question: ResearchQuestion
    plan: ResearchPlan
    sources: list[Source]
    documents: list[Document]
    evidence: list[Evidence]
    claims: list[Claim]
    retrieved_chunks: list[RetrievedChunk]
    citation_check: CitationCheckResult
    metadata: dict[str, str]
    markdown: str


def to_plain_dict(value: Any) -> Any:
    """Convert dataclass and enum values into JSON-friendly objects."""
    if isinstance(value, Enum):
        return value.value
    if hasattr(value, "__dataclass_fields__"):
        return {key: to_plain_dict(item) for key, item in asdict(value).items()}
    if isinstance(value, list):
        return [to_plain_dict(item) for item in value]
    if isinstance(value, dict):
        return {key: to_plain_dict(item) for key, item in value.items()}
    return value
