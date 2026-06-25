"""Dependency-free local web server for the Research Agent UI."""

from __future__ import annotations

import argparse
import json
import mimetypes
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from research_agent.searcher import SearchError
from research_agent.service import result_to_response, run_research


WEB_DIR = Path(__file__).resolve().parent / "web"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the Research Agent Web UI.")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind the local server to.")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind the local server to.")
    parser.add_argument("--output-dir", type=Path, default=Path("runs"), help="Directory for saved research traces.")
    return parser


def create_handler(output_dir: Path) -> type[BaseHTTPRequestHandler]:
    class ResearchAgentRequestHandler(BaseHTTPRequestHandler):
        server_version = "ResearchAgentMVP/0.1"

        def do_GET(self) -> None:
            path = urlparse(self.path).path
            if path == "/api/health":
                self._send_json({"status": "ok"})
                return

            if path == "/":
                path = "/index.html"

            asset_name = path.lstrip("/")
            if asset_name not in {"index.html", "styles.css", "app.js"}:
                self._send_error(HTTPStatus.NOT_FOUND, "Not found")
                return

            asset_path = WEB_DIR / asset_name
            if not asset_path.exists():
                self._send_error(HTTPStatus.NOT_FOUND, "Asset not found")
                return

            content_type = mimetypes.guess_type(asset_path.name)[0] or "application/octet-stream"
            payload = asset_path.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", f"{content_type}; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(payload)

        def do_POST(self) -> None:
            path = urlparse(self.path).path
            if path != "/api/research":
                self._send_error(HTTPStatus.NOT_FOUND, "Not found")
                return

            payload = self._read_json()
            question = str(payload.get("question", "")).strip()
            mode = str(payload.get("mode", "web")).strip().lower()
            llm_mode = str(payload.get("llm_mode", "gemini")).strip().lower()
            embedding_mode = str(payload.get("embedding_mode", "gemini")).strip().lower()
            rag = self._as_bool(payload.get("rag", True))
            save = self._as_bool(payload.get("save", True))

            if not question:
                self._send_error(HTTPStatus.BAD_REQUEST, "Question is required.")
                return
            if mode not in {"mock", "web", "auto"}:
                self._send_error(HTTPStatus.BAD_REQUEST, "Mode must be mock, web, or auto.")
                return
            if llm_mode not in {"mock", "gemini", "auto"}:
                self._send_error(HTTPStatus.BAD_REQUEST, "LLM mode must be mock, gemini, or auto.")
                return
            if embedding_mode not in {"hash", "gemini", "auto"}:
                self._send_error(HTTPStatus.BAD_REQUEST, "Embedding mode must be hash, gemini, or auto.")
                return

            try:
                result = run_research(
                    question=question,
                    mode=mode,
                    save=save,
                    output_dir=output_dir,
                    llm_mode=llm_mode,
                    embedding_mode=embedding_mode,
                    rag=rag,
                )
            except SearchError as exc:
                self._send_error(HTTPStatus.BAD_GATEWAY, str(exc))
                return
            except ValueError as exc:
                self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
                return
            except Exception as exc:  # noqa: BLE001 - convert server errors to JSON for the UI.
                self._send_error(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))
                return

            self._send_json(result_to_response(result))

        def log_message(self, format: str, *args: Any) -> None:
            return

        def _read_json(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0") or "0")
            if length <= 0:
                return {}
            raw = self.rfile.read(length).decode("utf-8")
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                return {}
            return parsed if isinstance(parsed, dict) else {}

        def _as_bool(self, value: Any) -> bool:
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                return value.strip().lower() in {"1", "true", "yes", "on"}
            return bool(value)

        def _send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
            raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(raw)

        def _send_error(self, status: HTTPStatus, message: str) -> None:
            self._send_json({"error": message}, status)

    return ResearchAgentRequestHandler


def run_server(host: str, port: int, output_dir: Path) -> ThreadingHTTPServer:
    handler = create_handler(output_dir)
    server = ThreadingHTTPServer((host, port), handler)
    return server


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    server = run_server(args.host, args.port, args.output_dir)
    url = f"http://{args.host}:{server.server_port}"
    print(f"Research Agent Web UI running at {url}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
