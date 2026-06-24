"""Command-line interface for the Research Agent MVP."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from research_agent.models import to_plain_dict
from research_agent.pipeline import ResearchPipeline
from research_agent.storage import ResearchRunStore


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
        default=os.getenv("RESEARCH_AGENT_SEARCH_MODE", "mock"),
        help="Search mode. mock is deterministic, web uses DuckDuckGo, auto tries web then falls back to mock.",
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
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    pipeline = ResearchPipeline(search_mode=args.mode)
    report = pipeline.run(args.question)

    saved_run = None
    if not args.no_save:
        saved_run = ResearchRunStore(args.output_dir).save(report)

    if args.json:
        output = json.dumps(to_plain_dict(report), ensure_ascii=False, indent=2)
    else:
        output = report.markdown

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output, encoding="utf-8")
    else:
        print(output)

    if saved_run:
        print(f"Saved reproducible run to: {saved_run.run_dir}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
