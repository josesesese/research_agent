"""FastAPI backend for the Research Agent."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

try:
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles
    from pydantic import BaseModel, Field
except ImportError as exc:  # pragma: no cover - exercised only when optional deps are missing.
    raise RuntimeError(
        "FastAPI backend dependencies are not installed. "
        "Install them with: python -m pip install -e .[web]"
    ) from exc

from research_agent.searcher import SearchError
from research_agent.service import result_to_response, run_research


WEB_DIR = Path(__file__).resolve().parent / "web"
DEFAULT_OUTPUT_DIR = Path(os.getenv("RESEARCH_AGENT_OUTPUT_DIR", "runs"))


class ResearchRequest(BaseModel):
    question: str = Field(..., min_length=1, description="Research question to investigate.")
    mode: Literal["mock", "web", "auto"] = Field("web", description="Search mode.")
    llm_mode: Literal["mock", "gemini", "auto"] = Field("gemini", description="Report synthesis mode.")
    embedding_mode: Literal["hash", "gemini", "auto"] = Field("gemini", description="Embedding mode for RAG.")
    rag: bool = Field(True, description="Whether to index documents and retrieve RAG context.")
    save: bool = Field(True, description="Whether to save report.md and trace.json.")


class HealthResponse(BaseModel):
    status: str
    service: str


def create_app(output_dir: Path | str = DEFAULT_OUTPUT_DIR) -> FastAPI:
    app = FastAPI(
        title="Research Agent API",
        version="0.1.0",
        description="Citation-grounded research reports with traceable evidence.",
    )
    resolved_output_dir = Path(output_dir)

    @app.get("/api/health", response_model=HealthResponse)
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "research-agent"}

    @app.post("/api/research")
    def research(request: ResearchRequest) -> dict[str, Any]:
        try:
            result = run_research(
                question=request.question,
                mode=request.mode,
                llm_mode=request.llm_mode,
                embedding_mode=request.embedding_mode,
                rag=request.rag,
                save=request.save,
                output_dir=resolved_output_dir,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except SearchError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except Exception as exc:  # noqa: BLE001 - surface backend failures as API errors.
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        return result_to_response(result)

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(WEB_DIR / "index.html")

    app.mount("/", StaticFiles(directory=WEB_DIR), name="web")
    return app


app = create_app()
