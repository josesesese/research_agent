"""CLI entrypoint for running the FastAPI backend with uvicorn."""

from __future__ import annotations

import argparse
import os
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the Research Agent FastAPI backend.")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind the FastAPI server to.")
    parser.add_argument("--port", type=int, default=8001, help="Port to bind the FastAPI server to.")
    parser.add_argument("--reload", action="store_true", help="Enable uvicorn reload mode.")
    parser.add_argument("--output-dir", type=Path, default=Path("runs"), help="Directory for saved research traces.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        import uvicorn
    except ImportError as exc:  # pragma: no cover - depends on optional deps.
        raise RuntimeError(
            "uvicorn is not installed. Install the FastAPI extras with: python -m pip install -e .[web]"
        ) from exc

    os.environ["RESEARCH_AGENT_OUTPUT_DIR"] = str(args.output_dir)

    uvicorn.run(
        "research_agent.api:create_app",
        factory=True,
        host=args.host,
        port=args.port,
        reload=args.reload,
        app_dir="src",
        env_file=None,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
