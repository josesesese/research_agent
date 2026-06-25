"""Optional Gemini-backed report synthesis."""

from __future__ import annotations

import logging
import os
import re

from research_agent.gemini_client import GeminiAPIError, GeminiClient, is_retryable_status
from research_agent.models import Claim, Evidence, ResearchPlan, RetrievedChunk, Source


logger = logging.getLogger(__name__)
DEFAULT_GEMINI_MODELS = ["gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.5-pro"]


class GeminiReportSynthesizer:
    """Generate the final report with a Gemini text model."""

    def __init__(
        self,
        client: GeminiClient | None = None,
        model: str | None = None,
        models: list[str] | None = None,
    ) -> None:
        self.client = client or GeminiClient()
        self.model = model or os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
        self.models = build_gemini_model_list(self.model, models)
        self.last_provider = "gemini"
        self.last_model = ""
        self.last_attempted_models: list[str] = []
        self.last_retry_count = 0
        self.last_failure_reason = ""

    def synthesize(
        self,
        plan: ResearchPlan,
        sources: list[Source],
        evidence: list[Evidence],
        claims: list[Claim],
        retrieved_chunks: list[RetrievedChunk],
    ) -> str:
        if not self.client.is_configured:
            raise GeminiAPIError(
                "GEMINI_API_KEY is not set. Set GEMINI_API_KEY for Gemini report synthesis, "
                "or use --llm-mode mock for offline tests."
            )

        prompt = build_report_prompt(plan, sources, evidence, claims, retrieved_chunks)
        self.last_model = ""
        self.last_attempted_models = []
        self.last_retry_count = 0
        self.last_failure_reason = ""
        errors: list[str] = []

        for model in self.models:
            self.last_attempted_models.append(model)
            try:
                text = self.client.create_interaction(model=model, input_text=prompt).strip()
                self.last_model = model
                self.last_retry_count += max(0, self.client.last_attempt_count - 1)
                logger.info("Gemini report synthesis succeeded with model=%s retries=%s", model, self.last_retry_count)
                return text + "\n"
            except GeminiAPIError as exc:
                self.last_retry_count += max(0, self.client.last_attempt_count - 1)
                reason = exc.brief()
                self.last_failure_reason = reason
                errors.append(f"{model}: {reason}")
                logger.warning("Gemini model failed: model=%s reason=%s", model, reason)
                if not should_try_next_gemini_model(exc):
                    break

        failure = "All configured Gemini models failed. " + " | ".join(errors)
        self.last_failure_reason = failure
        raise GeminiAPIError(failure, error_status="all_gemini_models_failed")


def build_gemini_model_list(primary_model: str, explicit_models: list[str] | None = None) -> list[str]:
    """Return a de-duplicated Gemini fallback list with the primary model first."""

    env_models = [
        item.strip()
        for item in os.getenv("GEMINI_MODELS", "").split(",")
        if item.strip()
    ]
    candidates = [primary_model]
    candidates.extend(explicit_models or env_models or DEFAULT_GEMINI_MODELS)
    return list(dict.fromkeys(candidates))


def should_try_next_gemini_model(error: GeminiAPIError) -> bool:
    """Decide whether another Gemini model may succeed after this error."""

    retryable_statuses = {"RESOURCE_EXHAUSTED", "UNAVAILABLE", "DEADLINE_EXCEEDED", "INTERNAL"}
    if error.status_code and is_retryable_status(error.status_code):
        return True
    if error.error_status in retryable_statuses:
        return True
    return False


def build_report_prompt(
    plan: ResearchPlan,
    sources: list[Source],
    evidence: list[Evidence],
    claims: list[Claim],
    retrieved_chunks: list[RetrievedChunk],
) -> str:
    source_numbers = {source.id: idx for idx, source in enumerate(sources, start=1)}

    source_lines = [
        f"[S{idx}] {source.title} | {source.url} | type={source.source_type.value} | date={source.published_at or 'unknown'}"
        for idx, source in enumerate(sources, start=1)
    ]
    evidence_lines = [
        f"- {item.id} [S{source_numbers.get(item.source_id, '?')}]: {item.quote}"
        for item in evidence
    ]
    claim_lines = [
        f"- {claim.topic}: {claim.text} | evidence={', '.join(claim.evidence_ids)}"
        for claim in claims
    ]
    chunk_lines = [f"- [S{source_numbers.get(chunk.source_id, '?')}]: {chunk.text[:900]}" for chunk in retrieved_chunks]
    sub_question_lines = [f"- {item.text} ({item.rationale})" for item in plan.sub_questions]
    comparison_instruction = build_comparison_table_instruction(plan.question.text)

    return f"""You are a citation-grounded research agent.

Write a concise Markdown research report for this question:
{plan.question.text}

Rules:
- Match the user's language when practical.
- Use only the evidence, retrieved chunks, and sources below.
- Every important factual claim must include source citations like [S1].
- If information is missing or uncertain, say so clearly.
- Do not invent pricing, dates, product capabilities, or source titles.
- Use only these report sections: Executive Summary, Comparison Snapshot, Evidence, Conclusion, Sources.
- Do not include a Citation Check section; the system adds that separately.
- Do not include retrieval ranks, vector scores, chunk scores, or implementation metadata in the final report.
- {comparison_instruction}

Research plan:
{chr(10).join(sub_question_lines)}

Sources:
{chr(10).join(source_lines)}

Extracted evidence:
{chr(10).join(evidence_lines)}

Structured claims:
{chr(10).join(claim_lines)}

Retrieved RAG chunks:
{chr(10).join(chunk_lines) if chunk_lines else '- No retrieved chunks.'}
"""


def build_comparison_table_instruction(question: str) -> str:
    match = re.search(r"\bcompare\s+(.+?)\s+and\s+(.+?)\s*$", question, flags=re.IGNORECASE)
    if not match:
        return (
            "In Comparison Snapshot, output a valid Markdown table with this exact header: "
            "| Feature | Finding | Evidence |"
        )
    left = match.group(1).strip(" .,:;")
    right = match.group(2).strip(" .,:;")
    if not left or not right:
        return (
            "In Comparison Snapshot, output a valid Markdown table with this exact header: "
            "| Feature | Finding | Evidence |"
        )
    return (
        "In Comparison Snapshot, output a valid Markdown table with this exact header: "
        f"| Feature | {left} | {right} |. Include the separator row | --- | --- | --- |."
    )
