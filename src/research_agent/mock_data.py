"""Mock source corpus for the MVP.

The content is intentionally small and transparent. It demonstrates the agent
pipeline without claiming to be live or exhaustive market research.
"""

from __future__ import annotations

from research_agent.models import Source, SourceType


CURSOR_WINDSURF_SOURCES: list[tuple[Source, str]] = [
    (
        Source(
            id="src_cursor_overview",
            title="Cursor product overview",
            url="mock://cursor/product-overview",
            source_type=SourceType.MOCK,
            published_at="2026-01-10",
            snippet="Cursor is positioned as an AI-first code editor for developers.",
        ),
        """
        Cursor is an AI-first code editor built around coding workflows. It
        emphasizes repository-aware chat, inline editing, autocomplete, and
        agent-style code changes inside an editor experience that feels close
        to VS Code. Teams commonly evaluate Cursor for fast code navigation,
        multi-file edits, and tight integration with existing developer habits.
        """,
    ),
    (
        Source(
            id="src_cursor_strengths",
            title="Cursor workflow notes",
            url="mock://cursor/workflow-notes",
            source_type=SourceType.MOCK,
            published_at="2026-01-11",
            snippet="Cursor is often strong when developers want AI in a familiar editor.",
        ),
        """
        Cursor is strongest for developers who want AI assistance without
        leaving a familiar editor model. Its value is most visible in codebase
        Q&A, refactoring, explaining unfamiliar files, and making targeted
        changes with human review. A common tradeoff is that teams still need
        clear review discipline because AI-generated diffs can look plausible
        while missing project-specific constraints.
        """,
    ),
    (
        Source(
            id="src_windsurf_overview",
            title="Windsurf product overview",
            url="mock://windsurf/product-overview",
            source_type=SourceType.MOCK,
            published_at="2026-01-10",
            snippet="Windsurf focuses on agentic coding flows and AI-assisted development.",
        ),
        """
        Windsurf is presented as an AI coding environment focused on agentic
        software development. It emphasizes flows where the assistant can keep
        context across a task, propose changes, and help developers move from
        intent to implementation with less manual prompting. Teams may evaluate
        Windsurf when they want a more guided AI coding workspace rather than
        only editor-level autocomplete.
        """,
    ),
    (
        Source(
            id="src_windsurf_strengths",
            title="Windsurf workflow notes",
            url="mock://windsurf/workflow-notes",
            source_type=SourceType.MOCK,
            published_at="2026-01-11",
            snippet="Windsurf can be attractive for guided, agentic workflows.",
        ),
        """
        Windsurf is strongest when the user wants the coding assistant to drive
        larger task flows, maintain task context, and suggest next steps. Its
        product story is less about being a drop-in editor clone and more about
        making AI collaboration feel central to the workspace. A tradeoff is
        that users who strongly prefer established editor muscle memory may
        need time to adapt.
        """,
    ),
    (
        Source(
            id="src_ai_coding_market",
            title="AI coding tools comparison notes",
            url="mock://market/ai-coding-tools",
            source_type=SourceType.MOCK,
            published_at="2026-01-12",
            snippet="AI coding tools differ by editor familiarity, autonomy, context, and pricing.",
        ),
        """
        AI coding tools are commonly compared across editor familiarity,
        autonomous task execution, repository context, collaboration controls,
        price, model options, and enterprise governance. Buyers should verify
        current pricing and policy details from official pages because these
        products change quickly.
        """,
    ),
]


GENERIC_SOURCES: list[tuple[Source, str]] = [
    (
        Source(
            id="src_generic_research",
            title="General research method note",
            url="mock://research/general-method",
            source_type=SourceType.MOCK,
            published_at="2026-01-01",
            snippet="Good research reports separate evidence, claims, and uncertainty.",
        ),
        """
        A reliable research report separates evidence from interpretation. It
        should list sources, quote or paraphrase relevant evidence, and mark
        uncertainty when the available sources are weak, stale, or incomplete.
        """,
    )
]


def load_mock_corpus(question: str) -> list[tuple[Source, str]]:
    normalized = question.lower()
    if "cursor" in normalized or "windsurf" in normalized:
        return CURSOR_WINDSURF_SOURCES
    return GENERIC_SOURCES
