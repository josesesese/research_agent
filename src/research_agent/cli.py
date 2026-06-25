"""Command-line interface for the Research Agent MVP."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from research_agent.gemini_client import GeminiAPIError
from research_agent.models import to_plain_dict
from research_agent.openai_client import OpenAIAPIError
from research_agent.searcher import SearchError
from research_agent.service import run_research


def configure_text_streams() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a citation-grounded Research Agent MVP.")
    parser.add_argument("question", help="Research question, for example: compare Cursor and Windsurf")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the full structured report as JSON instead of Markdown.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional path to write the Markdown or JSON result.",
    )
    parser.add_argument(
        "--mode",
        choices=["mock", "web", "auto"],
        default=os.getenv("RESEARCH_AGENT_SEARCH_MODE", "auto"),
        help="Search mode. auto tries live web search then falls back to mock; mock is for tests.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(os.getenv("RESEARCH_AGENT_OUTPUT_DIR", "runs")),
        help="Directory for reproducible run traces.",
    )
    parser.add_argument(
        "--no-save",
        action="store_true",
        help="Do not save report.md and trace.json for this run.",
    )
    parser.add_argument(
        "--llm-mode",
        choices=["mock", "gemini", "auto"],
        default=os.getenv("RESEARCH_AGENT_LLM_MODE", "gemini"),
        help="Report synthesis mode. gemini requires GEMINI_API_KEY; mock is for tests.",
    )
    parser.add_argument(
        "--embedding-mode",
        choices=["hash", "gemini", "auto"],
        default=os.getenv("RESEARCH_AGENT_EMBEDDING_MODE", "gemini"),
        help="Embedding mode for RAG. gemini requires GEMINI_API_KEY; hash is for tests.",
    )
    parser.add_argument(
        "--no-rag",
        action="store_true",
        help="Disable document chunking, vector indexing, and RAG retrieval.",
    )
    parser.add_argument(
        "--vector-store",
        type=Path,
        default=Path(os.getenv("RESEARCH_AGENT_VECTOR_STORE", "vector_store/research_agent_vectors.json")),
        help="Path to the local JSON vector database.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    configure_text_streams()
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        result = run_research(
            question=args.question,
            mode=args.mode,
            save=not args.no_save,
            output_dir=args.output_dir,
            llm_mode=args.llm_mode,
            embedding_mode=args.embedding_mode,
            rag=not args.no_rag,
            vector_store_path=args.vector_store,
        )
    except SearchError as exc:
        print(f"Search error: {exc}", file=sys.stderr)
        if args.mode == "web":
            print("--mode web uses only live web search and will not fall back to mock sources.", file=sys.stderr)
        else:
            print("Use --mode auto to allow mock fallback, or --mode mock for offline tests.", file=sys.stderr)
        return 3
    except (GeminiAPIError, OpenAIAPIError) as exc:
        brief = exc.brief() if hasattr(exc, "brief") else str(exc)
        print(f"Provider error: {brief}", file=sys.stderr)
        print(
            "Set GEMINI_API_KEY for the default Gemini path, or run offline with: "
            "--mode mock --llm-mode mock --embedding-mode hash",
            file=sys.stderr,
        )
        return 2
    report = result.report

    if args.json:
        output = json.dumps(to_plain_dict(report), ensure_ascii=False, indent=2)
    else:
        output = report.markdown

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output, encoding="utf-8")
    else:
        print(output)

    if result.saved_run:
        print(f"Saved reproducible run to: {result.saved_run.run_dir}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
