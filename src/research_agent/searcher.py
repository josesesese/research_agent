"""Search step for the MVP."""

from __future__ import annotations

import hashlib
import json
import os
from html import unescape
from html.parser import HTMLParser
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, quote_plus, urljoin, urlparse
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


class LiveWebSearcher:
    """Try real web search providers without falling back to mock data."""

    def __init__(self, searchers: list[Searcher] | None = None, max_results: int = 8) -> None:
        self.searchers = searchers or [DuckDuckGoSearcher(), BingSearcher(), WikipediaSearcher()]
        self.max_results = max_results
        self.last_used_mode = "unknown"
        self.last_provider = "unknown"
        self.last_failure_reason = ""

    def search(self, plan: ResearchPlan) -> list[Source]:
        failures: list[str] = []
        collected: list[Source] = []
        seen_urls: set[str] = set()
        self.last_used_mode = "unknown"
        self.last_provider = "unknown"
        self.last_failure_reason = ""

        for searcher in self.searchers:
            provider = searcher.__class__.__name__.replace("Searcher", "") or searcher.__class__.__name__
            try:
                sources = searcher.search(plan)
            except SearchError as exc:
                failures.append(f"{provider}: {exc}")
                continue

            if sources:
                self.last_used_mode = "web"
                if self.last_provider == "unknown":
                    self.last_provider = provider.lower()
                for source in sources:
                    if source.url in seen_urls:
                        continue
                    seen_urls.add(source.url)
                    collected.append(source)
                if len(collected) >= self.max_results:
                    break
                continue

            failures.append(f"{provider}: returned no usable results.")

        if collected:
            if failures:
                self.last_failure_reason = " | ".join(failures)
            return sort_sources_by_quality(collected)[: self.max_results]

        self.last_used_mode = "failed"
        self.last_failure_reason = " | ".join(failures) or "No live search providers were configured."
        raise SearchError(f"Live web search failed. {self.last_failure_reason}")


class AutoSearcher:
    """Try live web search first, then fall back to mock sources."""

    def __init__(self, web_searcher: Searcher | None = None, mock_searcher: Searcher | None = None) -> None:
        self.web_searcher = web_searcher or LiveWebSearcher()
        self.mock_searcher = mock_searcher or MockSearcher()
        self.last_used_mode = "unknown"
        self.last_failure_reason = ""

    def search(self, plan: ResearchPlan) -> list[Source]:
        self.last_failure_reason = ""
        try:
            sources = self.web_searcher.search(plan)
        except SearchError as exc:
            self.last_used_mode = "mock"
            self.last_failure_reason = str(exc)
            return self.mock_searcher.search(plan)
        if sources:
            self.last_used_mode = "web"
            return sources
        self.last_used_mode = "mock"
        self.last_failure_reason = "Live search returned no usable results."
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
        query_failures: list[str] = []

        for query in plan.search_queries:
            try:
                html = self._fetch_results_page(query)
            except SearchError as exc:
                query_failures.append(f"{query}: {exc}")
                continue

            results = parse_duckduckgo_results(html)
            if not results:
                query_failures.append(
                    f"{query}: DuckDuckGo returned no parseable results: {diagnose_duckduckgo_html(html)}"
                )
                continue

            accepted_for_query = 0
            for result in results:
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

            if accepted_for_query == 0:
                query_failures.append(f"{query}: DuckDuckGo results did not include new usable URLs.")

        if not sources:
            if query_failures:
                raise SearchError("DuckDuckGo search failed. " + " | ".join(query_failures))
            raise SearchError("DuckDuckGo search returned no usable results.")
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
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")[:500].strip()
            detail = f"HTTP {exc.code} {exc.reason}"
            if body:
                detail = f"{detail}; response body: {body}"
            raise SearchError(f"DuckDuckGo request failed: {detail}") from exc
        except URLError as exc:
            raise SearchError(f"DuckDuckGo request failed: {getattr(exc, 'reason', exc)}") from exc
        except TimeoutError as exc:
            raise SearchError(f"DuckDuckGo request timed out: {exc}") from exc
        except OSError as exc:
            raise SearchError(f"DuckDuckGo request failed: {exc}") from exc

    def _normalize_url(self, raw_url: str) -> str:
        if not raw_url:
            return ""

        absolute_url = urljoin("https://duckduckgo.com", unescape(raw_url))
        parsed = urlparse(absolute_url)
        query = parse_qs(parsed.query)
        if "uddg" in query and query["uddg"]:
            target = query["uddg"][0]
            target_domain = urlparse(target).netloc.lower()
            if target_domain and "duckduckgo.com" not in target_domain:
                return target
            return ""
        if parsed.scheme in {"http", "https"} and "duckduckgo.com" not in parsed.netloc.lower():
            return absolute_url
        return ""

    def _source_id(self, url: str) -> str:
        digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]
        return f"web_{digest}"


class BingSearcher:
    """Small Bing HTML search client used as a live-search backup."""

    search_url = "https://www.bing.com/search?q={query}"

    def __init__(self, max_results: int = 8, max_results_per_query: int = 2, timeout_seconds: int = 12) -> None:
        self.max_results = max_results
        self.max_results_per_query = max_results_per_query
        self.timeout_seconds = timeout_seconds

    def search(self, plan: ResearchPlan) -> list[Source]:
        sources: list[Source] = []
        seen_urls: set[str] = set()
        query_failures: list[str] = []

        for query in plan.search_queries:
            try:
                html = self._fetch_results_page(query)
            except SearchError as exc:
                query_failures.append(f"{query}: {exc}")
                continue

            results = parse_bing_results(html)
            if not results:
                query_failures.append(f"{query}: Bing returned no parseable results: {diagnose_bing_html(html)}")
                continue

            accepted_for_query = 0
            for result in results:
                url = self._normalize_url(result["url"])
                if not url or url in seen_urls:
                    continue

                seen_urls.add(url)
                accepted_for_query += 1
                sources.append(
                    Source(
                        id=self._source_id(url),
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

            if accepted_for_query == 0:
                query_failures.append(f"{query}: Bing results did not include new usable URLs.")

        if not sources:
            if query_failures:
                raise SearchError("Bing search failed. " + " | ".join(query_failures))
            raise SearchError("Bing search returned no usable results.")
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
                ),
                "Accept-Language": "en-US,en;q=0.9",
            },
        )

        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                charset = response.headers.get_content_charset() or "utf-8"
                return response.read().decode(charset, errors="replace")
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")[:500].strip()
            detail = f"HTTP {exc.code} {exc.reason}"
            if body:
                detail = f"{detail}; response body: {body}"
            raise SearchError(f"Bing request failed: {detail}") from exc
        except URLError as exc:
            raise SearchError(f"Bing request failed: {getattr(exc, 'reason', exc)}") from exc
        except TimeoutError as exc:
            raise SearchError(f"Bing request timed out: {exc}") from exc
        except OSError as exc:
            raise SearchError(f"Bing request failed: {exc}") from exc

    def _normalize_url(self, raw_url: str) -> str:
        if not raw_url:
            return ""

        absolute_url = unescape(raw_url)
        parsed = urlparse(absolute_url)
        if parsed.scheme in {"http", "https"} and "bing.com" not in parsed.netloc.lower():
            return absolute_url
        return ""

    def _source_id(self, url: str) -> str:
        digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]
        return f"web_{digest}"


class WikipediaSearcher:
    """Use Wikipedia OpenSearch as a real-source fallback for entity-heavy questions."""

    search_url = (
        "https://en.wikipedia.org/w/api.php?action=opensearch"
        "&search={query}&limit={limit}&namespace=0&format=json"
    )

    def __init__(self, max_results: int = 8, max_results_per_query: int = 2, timeout_seconds: int = 12) -> None:
        self.max_results = max_results
        self.max_results_per_query = max_results_per_query
        self.timeout_seconds = timeout_seconds

    def search(self, plan: ResearchPlan) -> list[Source]:
        sources: list[Source] = []
        seen_urls: set[str] = set()
        query_failures: list[str] = []

        for query in plan.search_queries:
            try:
                payload = self._fetch_results(query)
            except SearchError as exc:
                query_failures.append(f"{query}: {exc}")
                accepted = self._append_entity_fallback(query, sources, seen_urls, f"Wikipedia search error: {exc}")
                if accepted:
                    if len(sources) >= self.max_results:
                        return sources
                continue

            results = self._parse_results(payload)
            if not results:
                query_failures.append(f"{query}: Wikipedia OpenSearch returned no results.")
                accepted = self._append_entity_fallback(query, sources, seen_urls, "Wikipedia OpenSearch returned no results.")
                if accepted:
                    if len(sources) >= self.max_results:
                        return sources
                continue

            accepted_for_query = 0
            for result in results:
                url = result["url"]
                if not url or url in seen_urls:
                    continue

                seen_urls.add(url)
                accepted_for_query += 1
                sources.append(
                    Source(
                        id=self._source_id(url),
                        title=result["title"] or urlparse(url).path.rsplit("/", 1)[-1] or url,
                        url=url,
                        source_type=classify_source(url),
                        snippet=result.get("snippet", ""),
                    )
                )

                if len(sources) >= self.max_results:
                    return sources
                if accepted_for_query >= self.max_results_per_query:
                    break

            if accepted_for_query == 0:
                query_failures.append(f"{query}: Wikipedia OpenSearch results were duplicates or unusable.")

        if not sources:
            if query_failures:
                raise SearchError("Wikipedia OpenSearch failed. " + " | ".join(query_failures))
            raise SearchError("Wikipedia OpenSearch returned no usable results.")
        return sources

    def _fetch_results(self, query: str) -> object:
        url = self.search_url.format(query=quote_plus(query), limit=self.max_results_per_query)
        request = Request(
            url,
            headers={
                "User-Agent": "ResearchAgentMVP/0.1 (local demo)",
                "Accept": "application/json",
            },
        )

        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read().decode("utf-8", errors="replace")
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")[:500].strip()
            detail = f"HTTP {exc.code} {exc.reason}"
            if body:
                detail = f"{detail}; response body: {body}"
            raise SearchError(f"Wikipedia request failed: {detail}") from exc
        except URLError as exc:
            raise SearchError(f"Wikipedia request failed: {getattr(exc, 'reason', exc)}") from exc
        except TimeoutError as exc:
            raise SearchError(f"Wikipedia request timed out: {exc}") from exc
        except OSError as exc:
            raise SearchError(f"Wikipedia request failed: {exc}") from exc

        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise SearchError(f"Wikipedia returned invalid JSON: {exc}") from exc

    def _parse_results(self, payload: object) -> list[dict[str, str]]:
        if not isinstance(payload, list) or len(payload) < 4:
            return []
        titles = payload[1] if isinstance(payload[1], list) else []
        snippets = payload[2] if isinstance(payload[2], list) else []
        urls = payload[3] if isinstance(payload[3], list) else []

        results: list[dict[str, str]] = []
        for idx, raw_url in enumerate(urls):
            title = str(titles[idx]) if idx < len(titles) else ""
            snippet = str(snippets[idx]) if idx < len(snippets) else ""
            url = str(raw_url)
            parsed = urlparse(url)
            if parsed.scheme in {"http", "https"}:
                results.append({"title": title, "url": url, "snippet": snippet})
        return results

    def _append_entity_fallback(
        self,
        query: str,
        sources: list[Source],
        seen_urls: set[str],
        reason: str,
    ) -> bool:
        candidate = self._entity_source_candidate(query, reason)
        if not candidate or candidate.url in seen_urls:
            return False
        seen_urls.add(candidate.url)
        sources.append(candidate)
        return True

    def _entity_source_candidate(self, query: str, reason: str) -> Source | None:
        clean_query = " ".join(query.strip().split())
        lowered = clean_query.lower()
        if not clean_query or any(term in lowered for term in ["compare", "comparison", "pricing", "governance"]):
            return None
        if len(clean_query.split()) > 3:
            return None

        title = " ".join(part[:1].upper() + part[1:] for part in clean_query.split())
        path = quote(clean_query.replace(" ", "_"))
        url = f"https://en.wikipedia.org/wiki/{path}"
        return Source(
            id=self._source_id(url),
            title=title,
            url=url,
            source_type=classify_source(url),
            snippet=f"Entity page fallback because {reason}",
        )

    def _source_id(self, url: str) -> str:
        digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]
        return f"web_{digest}"


def parse_duckduckgo_results(html: str) -> list[dict[str, str]]:
    """Parse DuckDuckGo result HTML with multiple selector strategies."""

    results = parse_duckduckgo_results_with_beautifulsoup(html)
    if results:
        return results

    parser = DuckDuckGoResultParser()
    parser.feed(html)
    return parser.results


def parse_duckduckgo_results_with_beautifulsoup(html: str) -> list[dict[str, str]]:
    try:
        from bs4 import BeautifulSoup  # type: ignore[import-not-found]
    except ImportError:
        return []

    soup = BeautifulSoup(html, "html.parser")
    selectors = [
        "a.result__a",
        "a.result-link",
        "h2.result__title a",
        ".result__body a[href]",
        ".web-result a[href]",
        ".results_links a[href]",
        ".results_links_deep a[href]",
    ]
    results: list[dict[str, str]] = []
    seen: set[str] = set()

    for link in soup.select(",".join(selectors)):
        href = str(link.get("href") or "")
        title = link.get_text(" ", strip=True)
        if not href or not title:
            continue
        if href in seen:
            continue
        seen.add(href)
        container = link.find_parent(["article", "div", "li"])
        snippet = ""
        if container is not None:
            snippet_node = container.select_one(".result__snippet, .result-snippet, .snippet, .result__body")
            if snippet_node is not None:
                snippet = snippet_node.get_text(" ", strip=True)
        results.append({"title": title, "url": href, "snippet": snippet})

    return results


def diagnose_duckduckgo_html(html: str) -> str:
    lower = html.lower()
    markers = ["result__a", "result-link", "result__title", "result__snippet"]
    if not html.strip():
        return "empty response body"
    if any(term in lower for term in ["captcha", "anomaly", "bot detection", "verify you are human"]):
        return "DuckDuckGo returned an anti-bot or verification page"
    if "<title>duckduckgo</title>" in lower or "<title>duckduckgo</title>" in lower.replace(" ", ""):
        return "DuckDuckGo returned the generic search page without result markers"
    if not any(marker in lower for marker in markers):
        return f"no known result CSS markers found in {len(html)} characters"
    return "known result markers were present but no usable links were extracted"


def parse_bing_results(html: str) -> list[dict[str, str]]:
    """Parse Bing result HTML with multiple selector strategies."""

    results = parse_bing_results_with_beautifulsoup(html)
    if results:
        return results

    parser = BingResultParser()
    parser.feed(html)
    return parser.results


def parse_bing_results_with_beautifulsoup(html: str) -> list[dict[str, str]]:
    try:
        from bs4 import BeautifulSoup  # type: ignore[import-not-found]
    except ImportError:
        return []

    soup = BeautifulSoup(html, "html.parser")
    containers = soup.select("li.b_algo, .b_algo, #b_results > li")
    if not containers:
        containers = soup.select("main h2, #b_results h2, h2")

    results: list[dict[str, str]] = []
    seen: set[str] = set()
    for container in containers:
        link = container.select_one("h2 a[href], a[href]")
        if link is None:
            continue
        href = str(link.get("href") or "")
        title = link.get_text(" ", strip=True)
        if not href or not title or href in seen:
            continue
        seen.add(href)

        snippet = ""
        snippet_node = container.select_one(".b_caption p, p, .b_snippet")
        if snippet_node is not None:
            snippet = snippet_node.get_text(" ", strip=True)
        results.append({"title": title, "url": href, "snippet": snippet})

    return results


def diagnose_bing_html(html: str) -> str:
    lower = html.lower()
    markers = ["b_algo", "b_results", "<h2", "b_caption"]
    if not html.strip():
        return "empty response body"
    if any(term in lower for term in ["captcha", "verify", "unusual traffic", "not a robot"]):
        return "Bing returned an anti-bot or verification page"
    if not any(marker in lower for marker in markers):
        return f"no known result CSS markers found in {len(html)} characters"
    return "known result markers were present but no usable links were extracted"


class DuckDuckGoResultParser(HTMLParser):
    """Extract result title, URL, and snippet from DuckDuckGo's HTML page."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.results: list[dict[str, str]] = []
        self._in_link = False
        self._in_result_title = False
        self._in_snippet = False
        self._current_url = ""
        self._current_title: list[str] = []
        self._current_snippet: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {key: value or "" for key, value in attrs}
        class_name = attr_map.get("class", "")

        if tag == "h2" and "result__title" in class_name:
            self._in_result_title = True
            return

        if tag == "a" and (
            "result__a" in class_name or "result-link" in class_name or self._in_result_title
        ):
            self._in_link = True
            self._current_url = attr_map.get("href", "")
            self._current_title = []
            return

        if "result__snippet" in class_name or "result-snippet" in class_name or "snippet" in class_name:
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

        if tag == "h2" and self._in_result_title:
            self._in_result_title = False
            return

        if self._in_snippet:
            snippet = " ".join(part.strip() for part in self._current_snippet if part.strip())
            if snippet and self.results and not self.results[-1].get("snippet"):
                self.results[-1]["snippet"] = snippet
            self._in_snippet = False
            self._current_snippet = []


class BingResultParser(HTMLParser):
    """Extract result title, URL, and snippet from Bing's HTML results."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.results: list[dict[str, str]] = []
        self._in_result = False
        self._in_generic_heading = False
        self._result_depth = 0
        self._in_link = False
        self._in_snippet = False
        self._current_url = ""
        self._current_title: list[str] = []
        self._current_snippet: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {key: value or "" for key, value in attrs}
        class_name = attr_map.get("class", "")

        if tag == "li" and "b_algo" in class_name:
            self._start_result()
            return

        if tag == "h2" and not self._in_result:
            self._start_result()
            self._in_generic_heading = True
            return

        if not self._in_result:
            return

        self._result_depth += 1
        if tag == "a" and not self._current_url:
            href = attr_map.get("href", "")
            if href.startswith(("http://", "https://")):
                self._in_link = True
                self._current_url = href
                self._current_title = []
            return

        if tag == "p":
            self._in_snippet = True
            self._current_snippet = []

    def handle_data(self, data: str) -> None:
        if self._in_link:
            self._current_title.append(data)
        elif self._in_snippet:
            self._current_snippet.append(data)

    def handle_endtag(self, tag: str) -> None:
        if not self._in_result:
            return

        if tag == "a" and self._in_link:
            self._in_link = False
        elif tag == "p" and self._in_snippet:
            self._in_snippet = False
        elif tag == "h2" and self._in_generic_heading:
            self._finish_result()
            return

        self._result_depth -= 1
        if self._result_depth <= 0:
            self._finish_result()

    def _start_result(self) -> None:
        if self._in_result:
            self._finish_result()
        self._in_result = True
        self._result_depth = 1
        self._in_generic_heading = False
        self._in_link = False
        self._in_snippet = False
        self._current_url = ""
        self._current_title = []
        self._current_snippet = []

    def _finish_result(self) -> None:
        title = " ".join(part.strip() for part in self._current_title if part.strip())
        snippet = " ".join(part.strip() for part in self._current_snippet if part.strip())
        if self._current_url and title:
            self.results.append({"title": title, "url": self._current_url, "snippet": snippet})
        self._in_result = False
        self._result_depth = 0
        self._in_generic_heading = False
        self._in_link = False
        self._in_snippet = False
        self._current_url = ""
        self._current_title = []
        self._current_snippet = []


def classify_source(url: str) -> SourceType:
    domain = urlparse(url).netloc.lower()
    path = urlparse(url).path.lower()

    if any(
        host in domain
        for host in [
            "cursor.com",
            "windsurf.com",
            "windsurf.dev",
            "codeium.com",
            "openai.com",
            "youtube.com",
            "google.com",
            "bilibili.com",
        ]
    ):
        return SourceType.OFFICIAL
    if "docs" in domain or "developer" in domain or path.startswith("/docs") or "/docs/" in path:
        return SourceType.DOCUMENTATION
    if any(host in domain for host in ["reddit.com", "news.ycombinator.com", "stackoverflow.com"]):
        return SourceType.COMMUNITY
    if any(
        host in domain
        for host in [
            "techcrunch.com",
            "theverge.com",
            "wired.com",
            "bloomberg.com",
            "reuters.com",
            "apnews.com",
            "nytimes.com",
            "wsj.com",
            "bbc.com",
            "cnn.com",
            "forbes.com",
        ]
    ):
        return SourceType.NEWS
    if "wikipedia.org" in domain:
        return SourceType.UNKNOWN
    return SourceType.UNKNOWN


def sort_sources_by_quality(sources: list[Source]) -> list[Source]:
    """Rank sources for demos: official, docs, Wikipedia, news, then other pages."""

    def priority(source: Source) -> tuple[int, str]:
        domain = urlparse(source.url).netloc.lower()
        if source.source_type == SourceType.OFFICIAL:
            return (0, source.url)
        if source.source_type == SourceType.DOCUMENTATION:
            return (1, source.url)
        if "wikipedia.org" in domain:
            return (2, source.url)
        if source.source_type == SourceType.NEWS:
            return (3, source.url)
        if source.source_type == SourceType.REVIEW:
            return (4, source.url)
        if source.source_type == SourceType.COMMUNITY:
            return (5, source.url)
        return (6, source.url)

    return sorted(sources, key=priority)


def build_searcher(mode: str | None = None) -> Searcher:
    selected = (mode or os.getenv("RESEARCH_AGENT_SEARCH_MODE", "mock")).strip().lower()
    if selected == "mock":
        return MockSearcher()
    if selected in {"web", "live"}:
        return LiveWebSearcher()
    if selected == "duckduckgo":
        return DuckDuckGoSearcher()
    if selected == "bing":
        return BingSearcher()
    if selected == "wikipedia":
        return WikipediaSearcher()
    if selected == "auto":
        return AutoSearcher()
    raise ValueError(f"Unsupported search mode: {selected}. Use mock, web, or auto.")
