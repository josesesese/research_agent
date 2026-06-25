"""End-to-end research pipeline."""

from __future__ import annotations

import os
from pathlib import Path

from research_agent.citation_checker import CitationChecker
from research_agent.embeddings import EmbeddingProvider, HashEmbeddingProvider, build_embedding_provider
from research_agent.extractor import Extractor
from research_agent.gemini_client import GeminiAPIError
from research_agent.llm_synthesizer import GeminiReportSynthesizer
from research_agent.models import ResearchReport
from research_agent.planner import Planner
from research_agent.reader import Reader, WebReader
from research_agent.searcher import SearchError, Searcher, build_searcher
from research_agent.synthesizer import Synthesizer
from research_agent.vector_store import index_and_retrieve


class ResearchPipeline:
    """Coordinate the MVP research workflow."""

    def __init__(
        self,
        planner: Planner | None = None,
        searcher: Searcher | None = None,
        reader: Reader | None = None,
        extractor: Extractor | None = None,
        synthesizer: Synthesizer | None = None,
        citation_checker: CitationChecker | None = None,
        search_mode: str | None = None,
        llm_mode: str | None = None,
        embedding_mode: str | None = None,
        rag_enabled: bool = True,
        vector_store_path: Path | str | None = None,
        embedding_provider: EmbeddingProvider | None = None,
        llm_synthesizer: GeminiReportSynthesizer | None = None,
    ) -> None:
        self.search_mode = (search_mode or os.getenv("RESEARCH_AGENT_SEARCH_MODE", "auto")).strip().lower()
        self.llm_mode = (llm_mode or os.getenv("RESEARCH_AGENT_LLM_MODE", "gemini")).strip().lower()
        self.embedding_mode = (embedding_mode or os.getenv("RESEARCH_AGENT_EMBEDDING_MODE", "gemini")).strip().lower()
        self.rag_enabled = rag_enabled
        self.vector_store_path = Path(
            vector_store_path or os.getenv("RESEARCH_AGENT_VECTOR_STORE", "vector_store/research_agent_vectors.json")
        )
        self.planner = planner or Planner()
        self.searcher = searcher or build_searcher(self.search_mode)
        self.reader = reader or WebReader()
        self.extractor = extractor or Extractor()
        self.synthesizer = synthesizer or Synthesizer()
        self.citation_checker = citation_checker or CitationChecker()
        self.embedding_provider = embedding_provider or build_embedding_provider(self.embedding_mode)
        self.llm_synthesizer = llm_synthesizer or GeminiReportSynthesizer()

    def run(self, question: str) -> ResearchReport:
        plan = self.planner.plan(question)
        sources = self.searcher.search(plan)
        actual_search_mode = getattr(self.searcher, "last_used_mode", self.search_mode)
        search_failure_reason = getattr(self.searcher, "last_failure_reason", "")
        if self.search_mode in {"web", "live", "duckduckgo"}:
            mock_urls = [source.url for source in sources if source.url.startswith("mock://")]
            if mock_urls:
                raise SearchError("--mode web must use real URLs, but mock sources were returned.")
            if not sources:
                raise SearchError("--mode web did not return any real web sources.")

        runtime_notes: list[str] = []
        if actual_search_mode == "web" and search_failure_reason:
            runtime_notes.extend(
                [
                    "One live search provider failed before another live provider returned real sources.",
                    f"Live search provider failure reason: {search_failure_reason}",
                ]
            )
        elif self.search_mode == "auto" and actual_search_mode == "mock" and search_failure_reason:
            runtime_notes.extend(
                [
                    "Web search failed in auto mode, so the system fell back to deterministic mock sources.",
                    f"Web search failure reason: {search_failure_reason}",
                ]
            )

        documents = self.reader.read(plan.question.text, sources)
        retrieved_chunks = []
        actual_embedding_provider = "disabled"
        embedding_failure_reason = ""
        if self.rag_enabled:
            try:
                retrieved_chunks, actual_embedding_provider = index_and_retrieve(
                    question=plan.question.text,
                    documents=documents,
                    embedding_provider=self.embedding_provider,
                    vector_store_path=self.vector_store_path,
                )
            except GeminiAPIError as exc:
                embedding_failure_reason = exc.brief()
                retrieved_chunks, actual_embedding_provider = index_and_retrieve(
                    question=plan.question.text,
                    documents=documents,
                    embedding_provider=HashEmbeddingProvider(),
                    vector_store_path=self.vector_store_path,
                )
                actual_embedding_provider = "hash_fallback"

        evidence, claims = self.extractor.extract(documents)
        citation_check = self.citation_checker.check(claims, evidence)
        markdown = self.synthesizer.synthesize(plan, sources, evidence, claims, retrieved_chunks)
        actual_llm_mode = "template"
        llm_failure_reason = ""
        llm_provider = "template"
        llm_model = "template"
        llm_retry_count = "0"
        llm_attempted_models = ""

        if self.llm_mode in {"gemini", "auto"}:
            llm_provider = "gemini"
            try:
                markdown = self.llm_synthesizer.synthesize(plan, sources, evidence, claims, retrieved_chunks)
                actual_llm_mode = "gemini"
                llm_model = getattr(self.llm_synthesizer, "last_model", "") or getattr(
                    self.llm_synthesizer, "model", "unknown"
                )
                llm_retry_count = str(getattr(self.llm_synthesizer, "last_retry_count", 0))
                llm_attempted_models = ", ".join(getattr(self.llm_synthesizer, "last_attempted_models", []))
                runtime_notes.extend(
                    [
                        f"LLM provider: {llm_provider}",
                        f"LLM model: {llm_model}",
                        f"LLM retry count: {llm_retry_count}",
                    ]
                )
            except GeminiAPIError as exc:
                actual_llm_mode = "template_fallback"
                llm_failure_reason = exc.brief()
                llm_model = "template_fallback"
                llm_retry_count = str(getattr(self.llm_synthesizer, "last_retry_count", 0))
                llm_attempted_models = ", ".join(getattr(self.llm_synthesizer, "last_attempted_models", []))
                runtime_notes.extend(
                    [
                        f"LLM provider: {llm_provider}",
                        f"LLM model: {llm_model}",
                        f"Gemini models attempted: {llm_attempted_models or 'none'}",
                        f"LLM retry count: {llm_retry_count}",
                        "Gemini report generation failed, so the system returned the deterministic template report.",
                        f"Fallback reason: {llm_failure_reason}",
                        f"Failure reason: {llm_failure_reason}",
                    ]
                )

        if runtime_notes:
            markdown = prepend_runtime_notes(markdown, runtime_notes)

        if citation_check.issues:
            issue_lines = "\n".join(f"- {issue.claim_id}: {issue.message}" for issue in citation_check.issues)
            markdown += f"\n## Citation Check\n\nFailed:\n{issue_lines}\n"
        else:
            markdown += "\n## Citation Check\n\nPassed: every claim has at least one valid evidence reference.\n"

        return ResearchReport(
            question=plan.question,
            plan=plan,
            sources=sources,
            documents=documents,
            evidence=evidence,
            claims=claims,
            retrieved_chunks=retrieved_chunks,
            citation_check=citation_check,
            metadata={
                "requested_search_mode": self.search_mode,
                "actual_search_mode": actual_search_mode,
                "search_failure_reason": search_failure_reason,
                "requested_llm_mode": self.llm_mode,
                "actual_llm_mode": actual_llm_mode,
                "llm_provider": llm_provider,
                "llm_model": llm_model,
                "llm_retry_count": llm_retry_count,
                "llm_attempted_models": llm_attempted_models,
                "requested_embedding_mode": self.embedding_mode,
                "actual_embedding_provider": actual_embedding_provider,
                "embedding_failure_reason": embedding_failure_reason,
                "rag_enabled": str(self.rag_enabled).lower(),
                "vector_store_path": str(self.vector_store_path),
                "retrieved_chunks": str(len(retrieved_chunks)),
                "llm_failure_reason": llm_failure_reason,
            },
            markdown=markdown,
        )


def prepend_runtime_notes(markdown: str, notes: list[str]) -> str:
    note_lines = ["## Runtime Notes", ""]
    note_lines.extend(f"- {note}" for note in notes if note)
    return "\n".join(note_lines).strip() + "\n\n" + markdown
