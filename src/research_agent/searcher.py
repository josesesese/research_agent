"""Search step for the MVP."""

from __future__ import annotations

import hashlib
import os
from html import unescape
from html.parser import HTMLParser
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote_plus, urljoin, urlparse
from urllib.request import Request, urlopen

from research_agent.mock_data import load_mock_corpus
from research_agent.models import ResearchPlan, Source, SourceType


class Searcher(Protocol):
    def search(self, plan: ResearchPlan) -> list[Source]:
        """Return sources for a research plan."""


class SearchError(RuntimeError):
    """Raised when a live search provider cannot return usable results."""


class MockSearcher:
    """Return deterministic mock sources for repeatable demos and tests."""

    def search(self, plan: ResearchPlan) -> list[Source]:
        corpus = load_mock_corpus(plan.question.text)
        return [source for source, _ in corpus]


class AutoSearcher:
    """Try live web search first, then fall back to mock sources."""

    def __init__(self, web_searcher: Searcher | None = None, mock_searcher: Searcher | None = None) -> None:
        self.web_searcher = web_searcher or DuckDuckGoSearcher()
        self.mock_searcher = mock_searcher or MockSearcher()
        self.last_used_mode = "unknown"

    def search(self, plan: ResearchPlan) -> list[Source]:
        try:
            sources = self.web_searcher.search(plan)
        except SearchError:
            self.last_used_mode = "mock"
            return self.mock_searcher.search(plan)
        if sources:
            self.last_used_mode = "web"
            return sources
        self.last_used_mode = "mock"
        return self.mock_searcher.search(plan)


class DuckDuckGoSearcher:
    """Small DuckDuckGo HTML search client implemented with the standard library."""

    search_url = "https://duckduckgo.com/html/?q={query}"

    def __init__(self, max_results: int = 8, max_results_per_query: int = 2, timeout_seconds: int = 12) -> None:
        self.max_results = max_results
        self.max_results_per_query = max_results_per_query
        self.timeout_seconds = timeout_seconds

    def search(self, plan: ResearchPlan) -> list[Source]:
        sources: list[Source] = []
        seen_urls: set[str] = set()

        for query in plan.search_queries:
            try:
                html = self._fetch_results_page(query)
            except SearchError:
                continue

            parser = DuckDuckGoResultParser()
            parser.feed(html)

            accepted_for_query = 0
            for result in parser.results:
                url = self._normalize_url(result["url"])
                if not url or url in seen_urls:
                    continue

                seen_urls.add(url)
                accepted_for_query += 1
                source_id = self._source_id(url)
                sources.append(
                    Source(
                        id=source_id,
                        title=result["title"] or urlparse(url).netloc or url,
                        url=url,
                        source_type=classify_source(url),
                        snippet=result.get("snippet", ""),
                    )
                )

                if len(sources) >= self.max_results:
                    return sources
                if accepted_for_query >= self.max_results_per_query:
                    break

        if not sources:
            raise SearchError("Live search returned no usable results.")
        return sources

    def _fetch_results_page(self, query: str) -> str:
        url = self.search_url.format(query=quote_plus(query))
        request = Request(
            url,
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
                charset = response.headers.get_content_charset() or "utf-8"
                return response.read().decode(charset, errors="replace")
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            raise SearchError(f"Live search failed: {exc}") from exc

    def _normalize_url(self, raw_url: str) -> str:
        if not raw_url:
            return ""

        absolute_url = urljoin("https://duckduckgo.com", unescape(raw_url))
        parsed = urlparse(absolute_url)
        query = parse_qs(parsed.query)
        if "uddg" in query and query["uddg"]:
            return query["uddg"][0]
        if parsed.scheme in {"http", "https"}:
            return absolute_url
        return ""

    def _source_id(self, url: str) -> str:
        digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]
        return f"web_{digest}"


class DuckDuckGoResultParser(HTMLParser):
    """Extract result title, URL, and snippet from DuckDuckGo's HTML page."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.results: list[dict[str, str]] = []
        self._in_link = False
        self._in_snippet = False
        self._current_url = ""
        self._current_title: list[str] = []
        self._current_snippet: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {key: value or "" for key, value in attrs}
        class_name = attr_map.get("class", "")

        if tag == "a" and "result__a" in class_name:
            self._in_link = True
            self._current_url = attr_map.get("href", "")
            self._current_title = []
            return

        if "result__snippet" in class_name:
            self._in_snippet = True
            self._current_snippet = []

    def handle_data(self, data: str) -> None:
        if self._in_link:
            self._current_title.append(data)
        elif self._in_snippet:
            self._current_snippet.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._in_link:
            title = " ".join(part.strip() for part in self._current_title if part.strip())
            self.results.append({"title": title, "url": self._current_url, "snippet": ""})
            self._in_link = False
            self._current_url = ""
            self._current_title = []
            return

        if self._in_snippet:
            snippet = " ".join(part.strip() for part in self._current_snippet if part.strip())
            if snippet and self.results and not self.results[-1].get("snippet"):
                self.results[-1]["snippet"] = snippet
            self._in_snippet = False
            self._current_snippet = []


def classify_source(url: str) -> SourceType:
    domain = urlparse(url).netloc.lower()
    path = urlparse(url).path.lower()

    if any(host in domain for host in ["cursor.com", "windsurf.com", "windsurf.dev", "codeium.com", "openai.com"]):
        return SourceType.OFFICIAL
    if "docs" in domain or path.startswith("/docs") or "/docs/" in path:
        return SourceType.DOCUMENTATION
    if any(host in domain for host in ["reddit.com", "news.ycombinator.com", "stackoverflow.com"]):
        return SourceType.COMMUNITY
    if any(host in domain for host in ["techcrunch.com", "theverge.com", "wired.com", "bloomberg.com"]):
        return SourceType.NEWS
    return SourceType.UNKNOWN


def build_searcher(mode: str | None = None) -> Searcher:
    selected = (mode or os.getenv("RESEARCH_AGENT_SEARCH_MODE", "mock")).strip().lower()
    if selected == "mock":
        return MockSearcher()
    if selected in {"web", "live", "duckduckgo"}:
        return DuckDuckGoSearcher()
    if selected == "auto":
        return AutoSearcher()
    raise ValueError(f"Unsupported search mode: {selected}. Use mock, web, or auto.")
