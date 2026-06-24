"""End-to-end research pipeline."""

from __future__ import annotations

import os

from research_agent.citation_checker import CitationChecker
from research_agent.extractor import Extractor
from research_agent.models import ResearchReport
from research_agent.planner import Planner
from research_agent.reader import Reader, WebReader
from research_agent.searcher import Searcher, build_searcher
from research_agent.synthesizer import Synthesizer


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
    ) -> None:
        self.search_mode = (search_mode or os.getenv("RESEARCH_AGENT_SEARCH_MODE", "mock")).strip().lower()
        self.planner = planner or Planner()
        self.searcher = searcher or build_searcher(self.search_mode)
        self.reader = reader or WebReader()
        self.extractor = extractor or Extractor()
        self.synthesizer = synthesizer or Synthesizer()
        self.citation_checker = citation_checker or CitationChecker()

    def run(self, question: str) -> ResearchReport:
        plan = self.planner.plan(question)
        sources = self.searcher.search(plan)
        actual_search_mode = getattr(self.searcher, "last_used_mode", self.search_mode)
        documents = self.reader.read(plan.question.text, sources)
        evidence, claims = self.extractor.extract(documents)
        citation_check = self.citation_checker.check(claims, evidence)
        markdown = self.synthesizer.synthesize(plan, sources, evidence, claims)

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
            citation_check=citation_check,
            metadata={
                "requested_search_mode": self.search_mode,
                "actual_search_mode": actual_search_mode,
            },
            markdown=markdown,
        )
