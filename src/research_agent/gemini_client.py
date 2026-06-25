"""Small Google Gemini REST client using only the Python standard library."""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


logger = logging.getLogger(__name__)


class GeminiAPIError(RuntimeError):
    """Raised when a Gemini API request fails."""

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        error_status: str | None = None,
        raw_body: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error_status = error_status
        self.raw_body = raw_body

    def brief(self) -> str:
        label = self.error_status or "gemini_api_error"
        if self.status_code:
            return f"{label} (HTTP {self.status_code}): {self}"
        return f"{label}: {self}"


class GeminiClient:
    """Minimal Gemini client for generateContent and embeddings."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout_seconds: int = 60,
        max_retries: int | None = None,
        retry_backoff_seconds: float | None = None,
    ) -> None:
        self.api_key = os.getenv("GEMINI_API_KEY", "") if api_key is None else api_key
        self.base_url = (
            base_url or os.getenv("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta")
        ).rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries if max_retries is not None else int(os.getenv("GEMINI_MAX_RETRIES", "3"))
        self.retry_backoff_seconds = (
            retry_backoff_seconds
            if retry_backoff_seconds is not None
            else float(os.getenv("GEMINI_RETRY_BACKOFF_SECONDS", "1.0"))
        )
        self.max_retry_backoff_seconds = float(os.getenv("GEMINI_RETRY_MAX_BACKOFF_SECONDS", "8.0"))
        self.last_attempt_count = 0

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)

    def create_interaction(self, model: str, input_text: str) -> str:
        data = self._post(
            f"/models/{model}:generateContent",
            {
                "contents": [
                    {
                        "parts": [
                            {
                                "text": input_text,
                            }
                        ]
                    }
                ]
            },
        )
        return extract_gemini_text(data)

    def create_embeddings(
        self,
        model: str,
        texts: list[str],
        dimensions: int | None = None,
    ) -> list[list[float]]:
        if not texts:
            return []

        requests: list[dict[str, Any]] = []
        model_name = f"models/{model}"
        for text in texts:
            item: dict[str, Any] = {
                "model": model_name,
                "content": {
                    "parts": [{"text": text}],
                },
            }
            if dimensions:
                item["output_dimensionality"] = dimensions
            requests.append(item)

        data = self._post(f"/models/{model}:batchEmbedContents", {"requests": requests})
        embeddings = extract_gemini_embeddings(data)
        if len(embeddings) != len(texts):
            raise GeminiAPIError("Gemini embedding response did not include one vector for every input.")
        return embeddings

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.api_key:
            raise GeminiAPIError(
                "GEMINI_API_KEY is not set. Set GEMINI_API_KEY for Gemini generation, "
                "or use --mode mock --llm-mode mock --embedding-mode hash for offline tests.",
                error_status="missing_api_key",
            )

        body = json.dumps(payload).encode("utf-8")
        request = Request(
            f"{self.base_url}{path}",
            data=body,
            headers={
                "x-goog-api-key": self.api_key,
                "Content-Type": "application/json",
            },
            method="POST",
        )

        raw = self._post_with_retry(request)

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise GeminiAPIError("Gemini API returned invalid JSON.") from exc
        if not isinstance(parsed, dict):
            raise GeminiAPIError("Gemini API returned an unexpected response shape.")
        return parsed

    def _post_with_retry(self, request: Request) -> str:
        attempts = max(1, self.max_retries)
        last_error: GeminiAPIError | None = None
        self.last_attempt_count = 0

        for attempt in range(1, attempts + 1):
            self.last_attempt_count = attempt
            try:
                with self._open_url(request) as response:
                    return response.read().decode("utf-8")
            except HTTPError as exc:
                error_body = exc.read().decode("utf-8", errors="replace")
                message, status = parse_gemini_error_body(error_body)
                last_error = GeminiAPIError(
                    message=f"Gemini API request failed after attempt {attempt}/{attempts}: {message}",
                    status_code=exc.code,
                    error_status=status,
                    raw_body=error_body,
                )
                if not is_retryable_status(exc.code) or attempt >= attempts:
                    raise last_error from exc
                logger.warning("Retryable Gemini HTTP error on attempt %s/%s: %s", attempt, attempts, last_error.brief())
            except (URLError, TimeoutError, OSError) as exc:
                last_error = GeminiAPIError(
                    f"Gemini API request failed after attempt {attempt}/{attempts}: {exc}",
                    error_status="network_error",
                )
                if attempt >= attempts:
                    raise last_error from exc
                logger.warning("Retryable Gemini network error on attempt %s/%s: %s", attempt, attempts, exc)

            sleep_seconds = min(
                self.max_retry_backoff_seconds,
                self.retry_backoff_seconds * (2 ** (attempt - 1)),
            )
            if sleep_seconds > 0:
                time.sleep(sleep_seconds)

        if last_error:
            raise last_error
        raise GeminiAPIError("Gemini API request failed for an unknown reason.")

    def _open_url(self, request: Request):
        return urlopen(request, timeout=self.timeout_seconds)


def extract_gemini_text(data: dict[str, Any]) -> str:
    output_text = data.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()

    candidates = data.get("candidates", [])
    parts: list[str] = []
    for candidate in candidates:
        content = candidate.get("content", {}) if isinstance(candidate, dict) else {}
        for part in content.get("parts", []):
            text = part.get("text") if isinstance(part, dict) else None
            if isinstance(text, str) and text.strip():
                parts.append(text.strip())

    if parts:
        return "\n\n".join(parts)
    debug_payload = json.dumps(data, ensure_ascii=False, indent=2)[:4000]
    raise GeminiAPIError(
        f"Gemini response did not contain output text. Parsed response: {debug_payload}",
        raw_body=debug_payload,
    )


def extract_gemini_embeddings(data: dict[str, Any]) -> list[list[float]]:
    embeddings: list[list[float]] = []
    for item in data.get("embeddings", []):
        values = item.get("values") if isinstance(item, dict) else None
        if isinstance(values, list):
            embeddings.append([float(value) for value in values])
            continue
        nested = item.get("embedding") if isinstance(item, dict) else None
        if isinstance(nested, dict) and isinstance(nested.get("values"), list):
            embeddings.append([float(value) for value in nested["values"]])
    return embeddings


def parse_gemini_error_body(error_body: str) -> tuple[str, str | None]:
    try:
        payload = json.loads(error_body)
    except json.JSONDecodeError:
        return error_body[:500], None

    error = payload.get("error") if isinstance(payload, dict) else None
    if not isinstance(error, dict):
        return error_body[:500], None

    message = str(error.get("message") or "Unknown Gemini API error.")
    status = error.get("status")
    return message, str(status) if status else None


def is_retryable_status(status_code: int) -> bool:
    return status_code == 429 or 500 <= status_code <= 599
