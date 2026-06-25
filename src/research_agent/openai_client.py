"""Small OpenAI REST client using only the Python standard library."""

from __future__ import annotations

import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class OpenAIAPIError(RuntimeError):
    """Raised when an OpenAI API request fails."""

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        error_type: str | None = None,
        error_code: str | None = None,
        raw_body: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error_type = error_type
        self.error_code = error_code
        self.raw_body = raw_body

    @property
    def is_quota_error(self) -> bool:
        return self.status_code == 429 or self.error_code in {"insufficient_quota", "rate_limit_exceeded"}

    def brief(self) -> str:
        label = self.error_code or self.error_type or "openai_api_error"
        if self.status_code:
            return f"{label} (HTTP {self.status_code}): {self}"
        return f"{label}: {self}"


class OpenAIClient:
    """Minimal client for Responses API and Embeddings API."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout_seconds: int = 60,
    ) -> None:
        self.api_key = os.getenv("OPENAI_API_KEY", "") if api_key is None else api_key
        self.base_url = (base_url or os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")).rstrip("/")
        self.timeout_seconds = timeout_seconds

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)

    def create_response(self, model: str, input_text: str) -> str:
        payload = {
            "model": model,
            "input": input_text,
        }
        data = self._post("/responses", payload)
        return extract_response_text(data)

    def create_embeddings(
        self,
        model: str,
        texts: list[str],
        dimensions: int | None = None,
    ) -> list[list[float]]:
        payload: dict[str, Any] = {
            "model": model,
            "input": texts,
            "encoding_format": "float",
        }
        if dimensions:
            payload["dimensions"] = dimensions

        data = self._post("/embeddings", payload)
        embeddings = [item["embedding"] for item in sorted(data.get("data", []), key=lambda item: item["index"])]
        if len(embeddings) != len(texts):
            raise OpenAIAPIError("Embedding response did not include one vector for every input.")
        return embeddings

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.api_key:
            raise OpenAIAPIError(
                "OPENAI_API_KEY is not set. Set OPENAI_API_KEY for the default OpenAI path, "
                "or use --mode mock --llm-mode mock --embedding-mode hash for offline tests.",
                error_code="missing_api_key",
            )

        body = json.dumps(payload).encode("utf-8")
        request = Request(
            f"{self.base_url}{path}",
            data=body,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read().decode("utf-8")
        except HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            message, error_type, error_code = parse_openai_error_body(error_body)
            raise OpenAIAPIError(
                message=f"OpenAI API request failed: {message}",
                status_code=exc.code,
                error_type=error_type,
                error_code=error_code,
                raw_body=error_body,
            ) from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise OpenAIAPIError(f"OpenAI API request failed: {exc}", error_code="network_error") from exc

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise OpenAIAPIError("OpenAI API returned invalid JSON.") from exc
        if not isinstance(parsed, dict):
            raise OpenAIAPIError("OpenAI API returned an unexpected response shape.")
        return parsed


def extract_response_text(data: dict[str, Any]) -> str:
    """Extract text from common Responses API response shapes."""
    output_text = data.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()

    parts: list[str] = []
    for item in data.get("output", []):
        if not isinstance(item, dict):
            continue
        for content in item.get("content", []):
            if not isinstance(content, dict):
                continue
            text = content.get("text")
            if isinstance(text, str) and text.strip():
                parts.append(text.strip())

    if parts:
        return "\n\n".join(parts)
    raise OpenAIAPIError("OpenAI response did not contain output text.")


def parse_openai_error_body(error_body: str) -> tuple[str, str | None, str | None]:
    try:
        payload = json.loads(error_body)
    except json.JSONDecodeError:
        return error_body[:500], None, None

    error = payload.get("error") if isinstance(payload, dict) else None
    if not isinstance(error, dict):
        return error_body[:500], None, None

    message = str(error.get("message") or "Unknown OpenAI API error.")
    error_type = error.get("type")
    error_code = error.get("code")
    return message, str(error_type) if error_type else None, str(error_code) if error_code else None
