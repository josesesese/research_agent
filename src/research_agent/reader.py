"""Document reading step."""

from __future__ import annotations

import logging
import re
from html.parser import HTMLParser
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from research_agent.mock_data import load_mock_corpus
from research_agent.models import Document, Source


logger = logging.getLogger(__name__)


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
            text = self._extract_html_text(raw, source.url)

        if not text:
            text = source.snippet or f"No readable text extracted for {source.url}."

        return Document(source=source, text=text[: self.max_chars])

    def _extract_html_text(self, html: str, url: str = "") -> str:
        """Extract readable text, using stronger optional libraries when installed."""

        if is_wikipedia_url(url):
            text = self._extract_wikipedia_text(html)
            if text:
                return text

        for name, extractor in [
            ("trafilatura", extract_with_trafilatura),
            ("readability-lxml", extract_with_readability),
            ("beautifulsoup4", extract_with_beautifulsoup),
        ]:
            text = extractor(html)
            if text:
                logger.debug("Extracted readable text with %s", name)
                return text

        parser = HTMLTextExtractor()
        parser.feed(html)
        return self._normalize_text(" ".join(parser.text_parts))

    def _extract_wikipedia_text(self, html: str) -> str:
        text = extract_wikipedia_with_beautifulsoup(html)
        if text:
            return text
        parser = WikipediaArticleExtractor()
        parser.feed(html)
        return self._normalize_text(" ".join(parser.text_parts))

    def _normalize_text(self, text: str) -> str:
        return re.sub(r"\s+", " ", text).strip()


def is_wikipedia_url(url: str) -> bool:
    return "wikipedia.org" in urlparse(url).netloc.lower()


def normalize_extracted_text(text: str) -> str:
    cleaned = re.sub(r"\[\s*(edit|citation needed)\s*\]", " ", text, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def extract_with_trafilatura(html: str) -> str:
    """Extract readable text with trafilatura when available."""

    try:
        import trafilatura  # type: ignore[import-not-found]
    except ImportError:
        return ""

    extracted = trafilatura.extract(
        html,
        include_comments=False,
        include_tables=False,
        favor_precision=True,
    )
    return normalize_extracted_text(extracted or "")


def extract_with_readability(html: str) -> str:
    """Extract readable text with readability-lxml when available."""

    try:
        from readability import Document as ReadabilityDocument  # type: ignore[import-not-found]
    except ImportError:
        return ""

    try:
        summary_html = ReadabilityDocument(html).summary()
    except Exception as exc:  # noqa: BLE001 - optional parser can fail on malformed HTML.
        logger.debug("readability-lxml extraction failed: %s", exc)
        return ""
    return extract_with_beautifulsoup(summary_html) or extract_with_html_parser(summary_html)


def extract_with_beautifulsoup(html: str) -> str:
    """Extract text with BeautifulSoup when available."""

    try:
        from bs4 import BeautifulSoup  # type: ignore[import-not-found]
    except ImportError:
        return ""

    soup = BeautifulSoup(html, "html.parser")
    remove_noise_nodes(soup)
    root = soup.find("article") or soup.find("main") or soup.body or soup
    return normalize_extracted_text(root.get_text(" ", strip=True))


def extract_wikipedia_with_beautifulsoup(html: str) -> str:
    """Extract only Wikipedia article body text with BeautifulSoup when available."""

    try:
        from bs4 import BeautifulSoup  # type: ignore[import-not-found]
    except ImportError:
        return ""

    soup = BeautifulSoup(html, "html.parser")
    body = soup.select_one(".mw-parser-output")
    if body is None:
        return ""
    remove_noise_nodes(body)
    parts: list[str] = []
    for node in body.find_all(["p", "h2", "h3", "li"], recursive=True):
        if node.find_parent(["table", "nav", "footer", "aside"]):
            continue
        text = normalize_extracted_text(node.get_text(" ", strip=True))
        if not text:
            continue
        if len(text) < 30 and node.name == "li":
            continue
        parts.append(text)
    return normalize_extracted_text(" ".join(parts) or body.get_text(" ", strip=True))


def remove_noise_nodes(root) -> None:
    """Remove common navigation, metadata, and footer elements from a BeautifulSoup tree."""

    noisy_selectors = [
        "script",
        "style",
        "noscript",
        "svg",
        "canvas",
        "iframe",
        "form",
        "nav",
        "footer",
        "header",
        "aside",
        "table",
        "[role='navigation']",
        ".mw-editsection",
        ".mw-empty-elt",
        ".mw-indicators",
        ".mw-jump-link",
        ".mw-portlet-lang",
        ".mw-sidebar",
        ".noprint",
        ".mw-parser-output .noprint",
        ".vector-page-titlebar-toc",
        ".vector-toc",
        ".vector-dropdown",
        ".interlanguage-link",
        ".uls-language-list",
        ".navbox",
        ".vertical-navbox",
        ".sidebar",
        ".infobox",
        ".metadata",
        ".reflist",
        ".reference",
        ".references",
        ".toc",
        "#toc",
        ".hatnote",
        ".ambox",
        ".portal",
        ".sistersitebox",
        ".shortdescription",
        ".printfooter",
        ".catlinks",
    ]
    for node in root.select(",".join(noisy_selectors)):
        node.decompose()


def extract_with_html_parser(html: str) -> str:
    parser = HTMLTextExtractor()
    parser.feed(html)
    return normalize_extracted_text(" ".join(parser.text_parts))


class WikipediaArticleExtractor(HTMLParser):
    """Fallback extractor that keeps text inside Wikipedia's article body only."""

    ignored_class_fragments = {
        "mw-editsection",
        "navbox",
        "vertical-navbox",
        "sidebar",
        "infobox",
        "metadata",
        "reflist",
        "reference",
        "references",
        "toc",
        "hatnote",
        "ambox",
        "portal",
        "sistersitebox",
        "mw-portlet-lang",
        "interlanguage-link",
        "vector-toc",
        "shortdescription",
        "printfooter",
        "catlinks",
    }
    ignored_tags = {"script", "style", "noscript", "svg", "canvas", "iframe", "form", "nav", "footer", "header", "table", "aside"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.text_parts: list[str] = []
        self._capture_depth = 0
        self._ignore_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {key: value or "" for key, value in attrs}
        class_name = attr_map.get("class", "")
        element_id = attr_map.get("id", "")

        if self._is_article_body(class_name):
            self._capture_depth = 1
            return
        if not self._capture_depth:
            return

        self._capture_depth += 1
        if self._ignore_depth:
            self._ignore_depth += 1
            return
        if tag.lower() in self.ignored_tags or self._is_noise(class_name, element_id):
            self._ignore_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if not self._capture_depth:
            return
        if self._ignore_depth:
            self._ignore_depth -= 1
        self._capture_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._capture_depth or self._ignore_depth:
            return
        cleaned = data.strip()
        if cleaned:
            self.text_parts.append(cleaned)

    def _is_article_body(self, class_name: str) -> bool:
        return "mw-parser-output" in class_name.split()

    def _is_noise(self, class_name: str, element_id: str) -> bool:
        haystack = f"{class_name} {element_id}".lower()
        return any(fragment in haystack for fragment in self.ignored_class_fragments)


class HTMLTextExtractor(HTMLParser):
    """Tiny readable-text extractor for HTML pages."""

    ignored_tags = {"script", "style", "noscript", "svg", "canvas", "iframe", "form", "nav", "footer", "header", "aside"}

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
