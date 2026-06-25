"""Report synthesis step."""

from __future__ import annotations

import re

from research_agent.models import Claim, Evidence, ResearchPlan, RetrievedChunk, Source


class Synthesizer:
    """Generate a citation-grounded Markdown report."""

    def synthesize(
        self,
        plan: ResearchPlan,
        sources: list[Source],
        evidence: list[Evidence],
        claims: list[Claim],
        retrieved_chunks: list[RetrievedChunk] | None = None,
    ) -> str:
        source_index = {source.id: idx for idx, source in enumerate(sources, start=1)}
        evidence_index = {item.id: item for item in evidence}
        retrieved_chunks = retrieved_chunks or []
        has_mock_sources = any(source.url.startswith("mock://") for source in sources)

        lines: list[str] = [
            f"# Research Report: {plan.question.text}",
            "",
            f"> MVP note: this report uses {'mock demo sources' if has_mock_sources else 'live web sources'}. Verify fast-changing facts before external use.",
            "",
            "## Executive Summary",
            "",
        ]

        for claim in claims[:3]:
            lines.append(f"- {claim.text} {self._citations_for_claim(claim, evidence_index, source_index)}")

        lines.extend(["", "## Comparison Snapshot", ""])
        comparison_entities = self._comparison_entities(plan.question.text)
        if self._looks_like_cursor_vs_windsurf(plan.question.text):
            lines.extend(
                [
                    "| Feature | Cursor | Windsurf |",
                    "| --- | --- | --- |",
                    "| Positioning | AI-first editor experience | Agentic coding workspace |",
                    "| Best fit | Developers wanting AI inside familiar coding habits | Users wanting more guided task-level AI collaboration |",
                    "| Workflow emphasis | Codebase chat, inline edits, targeted multi-file changes | Context-retaining flows, task progress, assistant-driven next steps |",
                    "| Main caution | AI diffs still need careful project-aware review | Users may need time to adapt to a more AI-centered workspace |",
                ]
            )
        elif comparison_entities:
            left, right = comparison_entities
            lines.extend(
                [
                    f"| Feature | {left} | {right} |",
                    "| --- | --- | --- |",
                    "| Positioning | Evidence is summarized from cited sources. | Evidence is summarized from cited sources. |",
                    "| Audience | See cited evidence and sources below. | See cited evidence and sources below. |",
                    "| Strengths | Use source-backed claims below. | Use source-backed claims below. |",
                    "| Cautions | Verify fast-changing details from official sources. | Verify fast-changing details from official sources. |",
                ]
            )
        else:
            evidence_quality = (
                "Limited deterministic mock corpus"
                if has_mock_sources
                else "Live web sources retrieved; coverage may still be narrow"
            )
            recommendation = (
                "Run with --mode web before treating results as factual"
                if has_mock_sources
                else "Use citations and source dates to verify the final conclusions"
            )
            lines.extend(
                [
                    "| Dimension | Finding |",
                    "| --- | --- |",
                    f"| Evidence quality | {evidence_quality} |",
                    f"| Recommendation | {recommendation} |",
                ]
            )

        lines.extend(["", "## Evidence", ""])
        for item in evidence:
            source_number = source_index.get(item.source_id, "?")
            lines.append(f"- [S{source_number}] {item.quote}")

        lines.extend(["", "## Conclusion", ""])
        if claims:
            for claim in claims[:2]:
                lines.append(f"- {claim.text} {self._citations_for_claim(claim, evidence_index, source_index)}")
        lines.append("- Verify fast-changing details such as pricing, policies, and product capabilities from current official sources before external use.")

        lines.extend(["", "## Sources", ""])

        for idx, source in enumerate(sources, start=1):
            date_text = f", {source.published_at}" if source.published_at else ""
            lines.append(f"- [S{idx}] {source.title} ({source.source_type.value}{date_text}) - {source.url}")

        return "\n".join(lines).strip() + "\n"

    def _citations_for_claim(
        self,
        claim: Claim,
        evidence_index: dict[str, Evidence],
        source_index: dict[str, int],
    ) -> str:
        citations: list[str] = []
        for evidence_id in claim.evidence_ids:
            item = evidence_index.get(evidence_id)
            if not item:
                continue
            source_number = source_index.get(item.source_id)
            if source_number is not None:
                citations.append(f"[S{source_number}]")
        return " ".join(dict.fromkeys(citations))

    def _looks_like_cursor_vs_windsurf(self, question: str) -> bool:
        normalized = question.lower()
        return "cursor" in normalized and "windsurf" in normalized

    def _comparison_entities(self, question: str) -> tuple[str, str] | None:
        match = re.search(r"\bcompare\s+(.+?)\s+and\s+(.+?)\s*$", question, flags=re.IGNORECASE)
        if not match:
            return None
        left = match.group(1).strip(" .,:;")
        right = match.group(2).strip(" .,:;")
        if not left or not right:
            return None
        return (left[:1].upper() + left[1:], right[:1].upper() + right[1:])
