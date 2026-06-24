"""Document reading step."""

from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from research_agent.mock_data import load_mock_corpus
from research_agent.models import Document, Source


class Reader(Protocol):
    def read(self, question: str, sources: list[Source]) -> list[Document]:
        """Return cleaned documents for sources."""


class MockReader:
    """Read source text from the in-memory mock corpus."""

    def read(self, question: str, sources: list[Source]) -> list[Document]:
        corpus = {source.id: text.strip() for source, text in load_mock_corpus(question)}
        documents: list[Document] = []
        for source in sources:
            text = corpus.get(source.id, source.snippet)
            documents.append(Document(source=source, text=self._normalize_text(text)))
        return documents

    def _normalize_text(self, text: str) -> str:
        return " ".join(line.strip() for line in text.splitlines() if line.strip())


class WebReader:
    """Fetch and clean HTML pages with a snippet fallback."""

    def __init__(self, timeout_seconds: int = 12, max_chars: int = 12000) -> None:
        self.timeout_seconds = timeout_seconds
        self.max_chars = max_chars
        self.mock_reader = MockReader()

    def read(self, question: str, sources: list[Source]) -> list[Document]:
        documents: list[Document] = []
        mock_sources = [source for source in sources if source.url.startswith("mock://")]
        if mock_sources:
            documents.extend(self.mock_reader.read(question, mock_sources))

        for source in sources:
            if source.url.startswith("mock://"):
                continue

            if urlparse(source.url).scheme not in {"http", "https"}:
                documents.append(
                    Document(
                        source=source,
                        text=source.snippet,
                        read_error=f"Unsupported URL scheme: {source.url}",
                    )
                )
                continue

            document = self._fetch_document(source)
            documents.append(document)

        return documents

    def _fetch_document(self, source: Source) -> Document:
        request = Request(
            source.url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/126.0 Safari/537.36"
                )
            },
        )

        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                content_type = response.headers.get("content-type", "")
                charset = response.headers.get_content_charset() or "utf-8"
                raw = response.read().decode(charset, errors="replace")
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            fallback = source.snippet or f"Could not fetch page content for {source.url}."
            return Document(source=source, text=fallback, read_error=str(exc))

        if "html" not in content_type and "<html" not in raw[:500].lower():
            text = self._normalize_text(raw)
        else:
            text = self._extract_html_text(raw)

        if not text:
            text = source.snippet or f"No readable text extracted for {source.url}."

        return Document(source=source, text=text[: self.max_chars])

    def _extract_html_text(self, html: str) -> str:
        parser = HTMLTextExtractor()
        parser.feed(html)
        return self._normalize_text(" ".join(parser.text_parts))

    def _normalize_text(self, text: str) -> str:
        return re.sub(r"\s+", " ", text).strip()


class HTMLTextExtractor(HTMLParser):
    """Tiny readable-text extractor for HTML pages."""

    ignored_tags = {"script", "style", "noscript", "svg", "canvas", "iframe", "form", "nav", "footer"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.text_parts: list[str] = []
        self._ignore_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in self.ignored_tags:
            self._ignore_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in self.ignored_tags and self._ignore_depth:
            self._ignore_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._ignore_depth:
            return
        cleaned = data.strip()
        if cleaned:
            self.text_parts.append(cleaned)
