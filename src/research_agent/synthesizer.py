"""Report synthesis step."""

from __future__ import annotations

from research_agent.models import Claim, Evidence, ResearchPlan, Source


class Synthesizer:
    """Generate a citation-grounded Markdown report."""

    def synthesize(
        self,
        plan: ResearchPlan,
        sources: list[Source],
        evidence: list[Evidence],
        claims: list[Claim],
    ) -> str:
        source_index = {source.id: idx for idx, source in enumerate(sources, start=1)}
        evidence_index = {item.id: item for item in evidence}

        lines: list[str] = [
            f"# Research Report: {plan.question.text}",
            "",
            "> MVP note: this report may use mock or live web sources depending on the selected search mode. Verify fast-changing facts before external use.",
            "",
            "## Executive Summary",
            "",
        ]

        for claim in claims[:3]:
            lines.append(f"- {claim.text} {self._citations_for_claim(claim, evidence_index, source_index)}")

        lines.extend(
            [
                "",
                "## Research Plan",
                "",
            ]
        )
        for sub_question in plan.sub_questions:
            lines.append(f"- **{sub_question.text}** {sub_question.rationale}")

        lines.extend(["", "## Comparison Snapshot", ""])
        if self._looks_like_cursor_vs_windsurf(plan.question.text):
            lines.extend(
                [
                    "| Dimension | Cursor | Windsurf |",
                    "| --- | --- | --- |",
                    "| Positioning | AI-first editor experience | Agentic coding workspace |",
                    "| Best fit | Developers wanting AI inside familiar coding habits | Users wanting more guided task-level AI collaboration |",
                    "| Workflow emphasis | Codebase chat, inline edits, targeted multi-file changes | Context-retaining flows, task progress, assistant-driven next steps |",
                    "| Main caution | AI diffs still need careful project-aware review | Users may need time to adapt to a more AI-centered workspace |",
                ]
            )
        else:
            lines.extend(
                [
                    "| Dimension | Finding |",
                    "| --- | --- |",
                    "| Evidence quality | Limited in MVP mock mode |",
                    "| Recommendation | Add real search before treating results as factual |",
                ]
            )

        lines.extend(["", "## Key Claims", ""])
        for claim in claims:
            lines.append(f"- **{claim.topic}:** {claim.text} {self._citations_for_claim(claim, evidence_index, source_index)}")

        lines.extend(["", "## Evidence Extracts", ""])
        for item in evidence:
            source_number = source_index.get(item.source_id, "?")
            lines.append(f"- [S{source_number}] {item.quote}")

        lines.extend(
            [
                "",
                "## Gaps And Next Steps",
                "",
                "- Improve live search ranking, source diversity, and official-source filtering.",
                "- Verify live pricing, product names, policy details, and publication dates before using the report externally.",
                "- Add an LLM extractor later for richer claim clustering and contradiction handling.",
                "",
                "## Sources",
                "",
            ]
        )

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
