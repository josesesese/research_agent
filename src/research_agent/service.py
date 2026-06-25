"""Shared application service used by CLI and HTTP servers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from research_agent.models import ResearchReport, to_plain_dict
from research_agent.pipeline import ResearchPipeline
from research_agent.storage import ResearchRunStore, SavedRun


VALID_SEARCH_MODES = {"mock", "web", "auto"}


@dataclass(frozen=True)
class ResearchResult:
    report: ResearchReport
    saved_run: SavedRun | None


def run_research(
    question: str,
    mode: str = "auto",
    save: bool = True,
    output_dir: Path | str = "runs",
    llm_mode: str = "gemini",
    embedding_mode: str = "gemini",
    rag: bool = True,
    vector_store_path: Path | str = "vector_store/research_agent_vectors.json",
) -> ResearchResult:
    clean_question = question.strip()
    clean_mode = mode.strip().lower()
    clean_llm_mode = llm_mode.strip().lower()
    clean_embedding_mode = embedding_mode.strip().lower()

    if not clean_question:
        raise ValueError("Question is required.")
    if clean_mode not in VALID_SEARCH_MODES:
        raise ValueError("Mode must be mock, web, or auto.")
    if clean_llm_mode not in {"mock", "gemini", "auto"}:
        raise ValueError("LLM mode must be mock, gemini, or auto.")
    if clean_embedding_mode not in {"hash", "gemini", "auto"}:
        raise ValueError("Embedding mode must be hash, gemini, or auto.")

    report = ResearchPipeline(
        search_mode=clean_mode,
        llm_mode=clean_llm_mode,
        embedding_mode=clean_embedding_mode,
        rag_enabled=rag,
        vector_store_path=vector_store_path,
    ).run(clean_question)
    saved_run = ResearchRunStore(output_dir).save(report) if save else None
    return ResearchResult(report=report, saved_run=saved_run)


def result_to_response(result: ResearchResult) -> dict[str, Any]:
    response: dict[str, Any] = {"report": to_plain_dict(result.report), "saved_run": None}
    if result.saved_run:
        response["saved_run"] = {
            "run_id": result.saved_run.run_id,
            "run_dir": str(result.saved_run.run_dir),
            "report_path": str(result.saved_run.report_path),
            "trace_path": str(result.saved_run.trace_path),
        }
    return response
