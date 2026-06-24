"""Persistent run storage for reproducible research traces."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from research_agent.models import ResearchReport, to_plain_dict


@dataclass(frozen=True)
class SavedRun:
    run_id: str
    run_dir: Path
    report_path: Path
    trace_path: Path


class ResearchRunStore:
    """Save each research run as Markdown plus a structured JSON trace."""

    def __init__(self, output_dir: Path | str = "runs") -> None:
        self.output_dir = Path(output_dir)

    def save(self, report: ResearchReport) -> SavedRun:
        run_id = self._build_run_id(report.question.text)
        run_dir = self.output_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=False)

        report_path = run_dir / "report.md"
        trace_path = run_dir / "trace.json"

        report_path.write_text(report.markdown, encoding="utf-8")
        trace = {
            "run_id": run_id,
            "saved_at": datetime.now(UTC).isoformat(),
            "artifacts": {
                "report": report_path.name,
                "trace": trace_path.name,
            },
            "report": to_plain_dict(report),
        }
        trace_path.write_text(json.dumps(trace, ensure_ascii=False, indent=2), encoding="utf-8")

        return SavedRun(
            run_id=run_id,
            run_dir=run_dir,
            report_path=report_path,
            trace_path=trace_path,
        )

    def _build_run_id(self, question: str) -> str:
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        digest = hashlib.sha1(question.encode("utf-8")).hexdigest()[:8]
        slug = re.sub(r"[^a-zA-Z0-9]+", "-", question.lower()).strip("-")[:48]
        if slug:
            return f"{timestamp}-{slug}-{digest}"
        return f"{timestamp}-{digest}"
