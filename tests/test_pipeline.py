import json
import os
import socket
import time
import unittest
from importlib.util import find_spec
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from research_agent.citation_checker import CitationChecker
from research_agent.config import load_environment
from research_agent.embeddings import HashEmbeddingProvider
from research_agent.gemini_client import GeminiAPIError, GeminiClient, extract_gemini_embeddings, extract_gemini_text
from research_agent.llm_synthesizer import GeminiReportSynthesizer
from research_agent.llm_synthesizer import build_comparison_table_instruction, build_report_prompt
from research_agent.models import Claim, Evidence, Source, SourceType
from research_agent.pipeline import ResearchPipeline
from research_agent.reader import WebReader
from research_agent.searcher import (
    AutoSearcher,
    BingSearcher,
    DuckDuckGoSearcher,
    LiveWebSearcher,
    MockSearcher,
    SearchError,
    WikipediaSearcher,
    sort_sources_by_quality,
)
from research_agent.service import ResearchResult
from research_agent.storage import ResearchRunStore
from research_agent.vector_store import LocalVectorStore, build_chunks
from research_agent.web_server import run_server


class FailingSearcher:
    def search(self, plan):
        raise SearchError("intentional test failure")


class SuccessfulWebSearcher:
    def search(self, plan):
        return [
            Source(
                id="web_success",
                title="Example web source",
                url="https://example.com/research",
                source_type=SourceType.UNKNOWN,
                snippet="A real URL returned by a live provider.",
            )
        ]


class AlwaysFailingDuckDuckGoSearcher(DuckDuckGoSearcher):
    def _fetch_results_page(self, query: str) -> str:
        raise SearchError(f"network blocked for {query}")


class AlwaysFailingWikipediaSearcher(WikipediaSearcher):
    def _fetch_results(self, query: str) -> object:
        raise SearchError(f"network blocked for {query}")


class FailingLLMSynthesizer:
    def synthesize(self, plan, sources, evidence, claims, retrieved_chunks):
        raise GeminiAPIError("intentional test failure")


class FailingEmbeddingProvider:
    name = "gemini"

    def embed_texts(self, texts):
        raise GeminiAPIError("intentional embedding failure")


class FakeErrorBody:
    def __init__(self, data: bytes) -> None:
        self.data = data

    def read(self) -> bytes:
        return self.data

    def close(self) -> None:
        return None


class FakeResponse:
    def __init__(self, payload) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


class ResearchPipelineTests(unittest.TestCase):
    def test_load_environment_reads_env_file_without_overriding_shell(self) -> None:
        previous_key = os.environ.pop("GEMINI_API_KEY", None)
        previous_model = os.environ.pop("GEMINI_MODEL", None)
        try:
            with TemporaryDirectory() as temp_dir:
                env_path = Path(temp_dir) / ".env"
                env_path.write_text(
                    "GEMINI_API_KEY=test-secret\nGEMINI_MODEL=gemini-2.5-flash\n",
                    encoding="utf-8",
                )

                load_environment(env_path)

                self.assertEqual(os.getenv("GEMINI_API_KEY"), "test-secret")
                self.assertEqual(os.getenv("GEMINI_MODEL"), "gemini-2.5-flash")
        finally:
            if previous_key is None:
                os.environ.pop("GEMINI_API_KEY", None)
            else:
                os.environ["GEMINI_API_KEY"] = previous_key
            if previous_model is None:
                os.environ.pop("GEMINI_MODEL", None)
            else:
                os.environ["GEMINI_MODEL"] = previous_model

    def test_cursor_windsurf_report_has_sources_and_citations(self) -> None:
        report = self.mock_pipeline().run("compare Cursor and Windsurf")

        self.assertTrue(report.sources)
        self.assertTrue(report.documents)
        self.assertTrue(report.evidence)
        self.assertTrue(report.claims)
        self.assertTrue(report.retrieved_chunks)
        self.assertTrue(report.citation_check.passed)
        self.assertIn("Cursor", report.markdown)
        self.assertIn("Windsurf", report.markdown)
        self.assertIn("[S1]", report.markdown)
        self.assertIn("Citation Check", report.markdown)
        self.assertNotIn("rank=", report.markdown)
        self.assertNotIn("score=", report.markdown)

    def test_citation_checker_flags_missing_evidence(self) -> None:
        checker = CitationChecker()
        result = checker.check(
            claims=[Claim(id="cl_1", topic="Demo", text="A claim", evidence_ids=["missing"])],
            evidence=[Evidence(id="ev_1", source_id="src_1", quote="Quote", note="Note")],
        )

        self.assertFalse(result.passed)
        self.assertTrue(result.issues)

    def test_generic_question_marks_limited_evidence(self) -> None:
        report = self.mock_pipeline().run("research a niche developer tool")

        self.assertTrue(report.citation_check.passed)
        self.assertIn("Limited", report.markdown)

    def test_run_store_writes_report_and_trace(self) -> None:
        report = self.mock_pipeline().run("compare Cursor and Windsurf")

        with TemporaryDirectory() as tmp_dir:
            saved = ResearchRunStore(tmp_dir).save(report)

            self.assertTrue(saved.report_path.exists())
            self.assertTrue(saved.trace_path.exists())
            self.assertIn("Research Report", saved.report_path.read_text(encoding="utf-8"))
            self.assertIn("Cursor", saved.trace_path.read_text(encoding="utf-8"))

    def test_auto_searcher_falls_back_to_mock(self) -> None:
        plan = self.mock_pipeline().planner.plan("compare Cursor and Windsurf")
        searcher = AutoSearcher(web_searcher=FailingSearcher(), mock_searcher=MockSearcher())

        sources = searcher.search(plan)

        self.assertTrue(sources)
        self.assertTrue(all(source.url.startswith("mock://") for source in sources))
        self.assertEqual(searcher.last_used_mode, "mock")
        self.assertIn("intentional test failure", searcher.last_failure_reason)

    def test_auto_search_fallback_adds_runtime_notes(self) -> None:
        report = ResearchPipeline(
            search_mode="auto",
            searcher=AutoSearcher(web_searcher=FailingSearcher(), mock_searcher=MockSearcher()),
            llm_mode="mock",
            embedding_mode="hash",
        ).run("compare Cursor and Windsurf")

        self.assertEqual(report.metadata["actual_search_mode"], "mock")
        self.assertIn("intentional test failure", report.metadata["search_failure_reason"])
        self.assertIn("Runtime Notes", report.markdown)
        self.assertIn("Web search failure reason: intentional test failure", report.markdown)

    def test_web_mode_rejects_mock_sources(self) -> None:
        with self.assertRaises(SearchError) as context:
            ResearchPipeline(
                search_mode="web",
                searcher=MockSearcher(),
                llm_mode="mock",
                embedding_mode="hash",
            ).run("compare Cursor and Windsurf")

        self.assertIn("--mode web must use real URLs", str(context.exception))

    def test_duckduckgo_failure_preserves_query_errors(self) -> None:
        plan = self.mock_pipeline().planner.plan("compare Cursor and Windsurf")

        with self.assertRaises(SearchError) as context:
            AlwaysFailingDuckDuckGoSearcher().search(plan)

        message = str(context.exception)
        self.assertIn("DuckDuckGo search failed", message)
        self.assertIn("network blocked", message)
        self.assertIn(plan.search_queries[0], message)

    def test_duckduckgo_normalizer_filters_ad_redirects(self) -> None:
        searcher = DuckDuckGoSearcher()

        self.assertEqual(searcher._normalize_url("/y.js?ad_domain=example.com"), "")
        self.assertEqual(searcher._normalize_url("https://duckduckgo.com/y.js?u3=https%3A%2F%2Fads.example"), "")

    def test_duckduckgo_parser_supports_multiple_result_selectors(self) -> None:
        class FixtureDuckDuckGoSearcher(DuckDuckGoSearcher):
            def _fetch_results_page(self, query: str) -> str:
                return """
                <html><body>
                  <div class="web-result">
                    <h2 class="result__title">
                      <a href="/l/?uddg=https%3A%2F%2Fwww.youtube.com">YouTube</a>
                    </h2>
                    <a class="result-link" href="/l/?uddg=https%3A%2F%2Fwww.bilibili.com">Bilibili</a>
                    <a href="/y.js?ad_domain=example.com">Ad</a>
                    <div class="result__snippet">Video platform source.</div>
                  </div>
                </body></html>
                """

        plan = self.mock_pipeline().planner.plan("compare youtube and bilibili")
        sources = FixtureDuckDuckGoSearcher(max_results=4, max_results_per_query=4).search(plan)
        urls = {source.url for source in sources}

        self.assertIn("https://www.youtube.com", urls)
        self.assertIn("https://www.bilibili.com", urls)
        self.assertFalse(any("duckduckgo.com/y.js" in source.url for source in sources))

    def test_bing_parser_supports_multiple_result_selectors(self) -> None:
        class FixtureBingSearcher(BingSearcher):
            def _fetch_results_page(self, query: str) -> str:
                return """
                <html><body>
                  <ol id="b_results">
                    <li class="b_algo">
                      <h2><a href="https://www.youtube.com">YouTube</a></h2>
                      <div class="b_caption"><p>Official video platform.</p></div>
                    </li>
                    <li>
                      <h2><a href="https://www.bilibili.com">Bilibili</a></h2>
                      <p>Official video platform.</p>
                    </li>
                  </ol>
                </body></html>
                """

        plan = self.mock_pipeline().planner.plan("compare youtube and bilibili")
        sources = FixtureBingSearcher(max_results=4, max_results_per_query=4).search(plan)
        urls = {source.url for source in sources}

        self.assertIn("https://www.youtube.com", urls)
        self.assertIn("https://www.bilibili.com", urls)

    def test_live_web_searcher_keeps_provider_failure_reason_after_success(self) -> None:
        plan = self.mock_pipeline().planner.plan("compare youtube and bilibili")
        searcher = LiveWebSearcher(searchers=[FailingSearcher(), SuccessfulWebSearcher()])

        sources = searcher.search(plan)

        self.assertEqual(searcher.last_used_mode, "web")
        self.assertEqual(searcher.last_provider, "successfulweb")
        self.assertIn("intentional test failure", searcher.last_failure_reason)
        self.assertTrue(all(source.url.startswith("https://") for source in sources))

    def test_wikipedia_searcher_falls_back_to_entity_urls(self) -> None:
        plan = self.mock_pipeline().planner.plan("compare youtube and bilibili")
        sources = AlwaysFailingWikipediaSearcher().search(plan)
        urls = {source.url for source in sources}

        self.assertIn("https://en.wikipedia.org/wiki/youtube", urls)
        self.assertIn("https://en.wikipedia.org/wiki/bilibili", urls)
        self.assertTrue(all(source.url.startswith("https://") for source in sources))

    def test_hash_embedding_and_local_vector_store_retrieve_chunks(self) -> None:
        report = self.mock_pipeline().run("compare Cursor and Windsurf")
        chunks = build_chunks(report.documents, chunk_size=240, overlap=40)
        provider = HashEmbeddingProvider()

        with TemporaryDirectory() as tmp_dir:
            store = LocalVectorStore(Path(tmp_dir) / "vectors.json")
            store.upsert_chunks(chunks, provider.embed_texts([chunk.text for chunk in chunks]))
            query_vector = provider.embed_texts(["Cursor editor workflow"])[0]
            retrieved = store.search(query_vector, top_k=2)

            self.assertTrue(retrieved)
            self.assertLessEqual(len(retrieved), 2)

    def test_llm_auto_mode_falls_back_to_template(self) -> None:
        report = ResearchPipeline(
            search_mode="mock",
            llm_mode="auto",
            embedding_mode="hash",
            llm_synthesizer=FailingLLMSynthesizer(),
        ).run("compare Cursor and Windsurf")

        self.assertEqual(report.metadata["actual_llm_mode"], "template_fallback")
        self.assertIn("Research Report", report.markdown)

    def test_gemini_failure_returns_report_with_failure_reason(self) -> None:
        report = ResearchPipeline(
            search_mode="mock",
            llm_mode="gemini",
            embedding_mode="gemini",
            embedding_provider=FailingEmbeddingProvider(),
            llm_synthesizer=FailingLLMSynthesizer(),
        ).run("compare Cursor and Windsurf")

        self.assertEqual(report.metadata["actual_llm_mode"], "template_fallback")
        self.assertEqual(report.metadata["actual_embedding_provider"], "hash_fallback")
        self.assertIn("intentional test failure", report.metadata["llm_failure_reason"])
        self.assertIn("intentional embedding failure", report.metadata["embedding_failure_reason"])
        self.assertIn("Runtime Notes", report.markdown)
        self.assertIn("Failure reason", report.markdown)

    def test_extract_gemini_text_supports_output_shapes(self) -> None:
        direct = extract_gemini_text({"output_text": "hello"})
        nested = extract_gemini_text(
            {
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "text": "world",
                                }
                            ]
                        }
                    }
                ]
            }
        )

        self.assertEqual(direct, "hello")
        self.assertEqual(nested, "world")

    def test_extract_gemini_embeddings_supports_batch_shape(self) -> None:
        embeddings = extract_gemini_embeddings(
            {
                "embeddings": [
                    {"values": [0.1, 0.2]},
                    {"values": [0.3, 0.4]},
                ]
            }
        )

        self.assertEqual(embeddings, [[0.1, 0.2], [0.3, 0.4]])

    def test_extract_gemini_text_error_includes_response_payload(self) -> None:
        with self.assertRaises(GeminiAPIError) as context:
            extract_gemini_text({"candidates": [{"content": {"parts": []}, "finishReason": "SAFETY"}]})

        self.assertIn("Parsed response", str(context.exception))
        self.assertIn("SAFETY", str(context.exception))

    def test_pipeline_defaults_are_production_gemini_path(self) -> None:
        pipeline = ResearchPipeline()

        self.assertEqual(pipeline.search_mode, "auto")
        self.assertEqual(pipeline.llm_mode, "gemini")
        self.assertEqual(pipeline.embedding_mode, "gemini")
        self.assertEqual(pipeline.llm_synthesizer.model, "gemini-2.5-flash")

    def test_gemini_client_retries_transient_http_errors(self) -> None:
        attempts = {"count": 0}
        seen = {"url": "", "body": {}}

        class RetryGeminiClient(GeminiClient):
            def __init__(self) -> None:
                super().__init__(api_key="test-key", max_retries=2, retry_backoff_seconds=0)

            def _open_url(self, request):
                attempts["count"] += 1
                seen["url"] = request.full_url
                seen["body"] = json.loads(request.data.decode("utf-8"))
                if attempts["count"] == 1:
                    raise HTTPError(
                        request.full_url,
                        429,
                        "Too Many Requests",
                        {},
                        FakeErrorBody(b'{"error":{"message":"retry later","status":"RESOURCE_EXHAUSTED"}}'),
                    )
                return FakeResponse({"output_text": "ok"})

        client = RetryGeminiClient()

        self.assertEqual(client.create_interaction("gemini-2.5-flash", "hello"), "ok")
        self.assertEqual(attempts["count"], 2)
        self.assertIn("/models/gemini-2.5-flash:generateContent", seen["url"])
        self.assertEqual(seen["body"]["contents"][0]["parts"][0]["text"], "hello")
        self.assertNotIn("input", seen["body"])
        self.assertNotIn("model", seen["body"])

    def test_gemini_synthesizer_switches_models_after_503(self) -> None:
        attempts_by_model = {}

        class SwitchingGeminiClient(GeminiClient):
            def __init__(self) -> None:
                super().__init__(api_key="test-key", max_retries=2, retry_backoff_seconds=0)

            def _open_url(self, request):
                model = request.full_url.split("/models/", 1)[1].split(":generateContent", 1)[0]
                attempts_by_model[model] = attempts_by_model.get(model, 0) + 1
                if model == "gemini-2.5-flash":
                    raise HTTPError(
                        request.full_url,
                        503,
                        "Service Unavailable",
                        {},
                        FakeErrorBody(b'{"error":{"message":"High Demand","status":"UNAVAILABLE"}}'),
                    )
                return FakeResponse({"candidates": [{"content": {"parts": [{"text": "# Gemini report"}]}}]})

        synthesizer = GeminiReportSynthesizer(
            client=SwitchingGeminiClient(),
            models=["gemini-2.5-flash", "gemini-2.5-flash-lite"],
        )
        report = ResearchPipeline(
            search_mode="mock",
            llm_mode="gemini",
            embedding_mode="hash",
            llm_synthesizer=synthesizer,
        ).run("compare Cursor and Windsurf")

        self.assertEqual(report.metadata["actual_llm_mode"], "gemini")
        self.assertEqual(report.metadata["llm_model"], "gemini-2.5-flash-lite")
        self.assertEqual(report.metadata["llm_retry_count"], "1")
        self.assertIn("gemini-2.5-flash, gemini-2.5-flash-lite", report.metadata["llm_attempted_models"])
        self.assertEqual(attempts_by_model["gemini-2.5-flash"], 2)
        self.assertEqual(attempts_by_model["gemini-2.5-flash-lite"], 1)
        self.assertIn("LLM model: gemini-2.5-flash-lite", report.markdown)

    def test_prompt_requires_fixed_comparison_table_and_hides_scores(self) -> None:
        report = self.mock_pipeline().run("compare youtube and bilibili")
        prompt = build_report_prompt(
            report.plan,
            report.sources,
            report.evidence,
            report.claims,
            report.retrieved_chunks,
        )

        self.assertIn("| Feature | youtube | bilibili |", prompt)
        self.assertIn("Do not include retrieval ranks, vector scores, chunk scores", prompt)
        self.assertNotIn("rank=", prompt)
        self.assertNotIn("score=", prompt)

    def test_comparison_table_instruction_uses_feature_header(self) -> None:
        instruction = build_comparison_table_instruction("compare YouTube and Bilibili")

        self.assertIn("| Feature | YouTube | Bilibili |", instruction)

    def test_wikipedia_reader_extracts_article_body_without_navigation(self) -> None:
        html = """
        <html><body>
          <nav>Jump to content</nav>
          <div class="vector-sidebar">Sidebar</div>
          <div class="mw-parser-output">
            <div class="mw-editsection">Edit links</div>
            <table class="infobox"><tr><td>Infobox noise</td></tr></table>
            <p>YouTube is an online video sharing platform.</p>
            <div class="navbox">Navigation box</div>
            <p>Bilibili is a Chinese video sharing website.</p>
          </div>
          <footer>Footer text</footer>
        </body></html>
        """

        text = WebReader()._extract_html_text(html, "https://en.wikipedia.org/wiki/YouTube")

        self.assertIn("YouTube is an online video sharing platform.", text)
        self.assertIn("Bilibili is a Chinese video sharing website.", text)
        self.assertNotIn("Jump to content", text)
        self.assertNotIn("Edit links", text)
        self.assertNotIn("Infobox noise", text)
        self.assertNotIn("Footer text", text)

    def test_source_quality_sort_prefers_official_then_wikipedia(self) -> None:
        sources = [
            Source("wiki", "Wikipedia", "https://en.wikipedia.org/wiki/YouTube", SourceType.UNKNOWN),
            Source("other", "Other", "https://example.com/post", SourceType.UNKNOWN),
            Source("official", "YouTube", "https://www.youtube.com", SourceType.OFFICIAL),
            Source("news", "News", "https://www.reuters.com/technology/example", SourceType.NEWS),
        ]

        sorted_sources = sort_sources_by_quality(sources)

        self.assertEqual(sorted_sources[0].id, "official")
        self.assertEqual(sorted_sources[1].id, "wiki")
        self.assertEqual(sorted_sources[2].id, "news")

    def test_web_server_health_and_research_api(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            server = run_server("127.0.0.1", 0, Path(tmp_dir))
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base_url = f"http://127.0.0.1:{server.server_port}"

            try:
                with urlopen(f"{base_url}/api/health", timeout=5) as response:
                    health = json.loads(response.read().decode("utf-8"))
                self.assertEqual(health["status"], "ok")

                request = Request(
                    f"{base_url}/api/research",
                    data=json.dumps(
                        {
                            "question": "compare Cursor and Windsurf",
                            "mode": "mock",
                            "llm_mode": "mock",
                            "embedding_mode": "hash",
                            "rag": True,
                            "save": True,
                        }
                    ).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urlopen(request, timeout=10) as response:
                    payload = json.loads(response.read().decode("utf-8"))

                self.assertIn("report", payload)
                self.assertIn("saved_run", payload)
                self.assertIn("Cursor", payload["report"]["markdown"])
                self.assertEqual(payload["report"]["metadata"]["actual_llm_mode"], "template")
                self.assertTrue(Path(payload["saved_run"]["trace_path"]).exists())
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

    def test_web_server_passes_ui_modes_to_service(self) -> None:
        captured = {}
        report = self.mock_pipeline().run("compare Cursor and Windsurf")

        def fake_run_research(**kwargs):
            captured.update(kwargs)
            return ResearchResult(report=report, saved_run=None)

        with TemporaryDirectory() as tmp_dir, patch("research_agent.web_server.run_research", fake_run_research):
            server = run_server("127.0.0.1", 0, Path(tmp_dir))
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base_url = f"http://127.0.0.1:{server.server_port}"

            try:
                request = Request(
                    f"{base_url}/api/research",
                    data=json.dumps(
                        {
                            "question": "compare youtube and bilibili",
                            "mode": "web",
                            "llm_mode": "mock",
                            "embedding_mode": "hash",
                            "rag": False,
                            "save": False,
                        }
                    ).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urlopen(request, timeout=10) as response:
                    self.assertEqual(response.status, 200)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

        self.assertEqual(captured["question"], "compare youtube and bilibili")
        self.assertEqual(captured["mode"], "web")
        self.assertEqual(captured["llm_mode"], "mock")
        self.assertEqual(captured["embedding_mode"], "hash")
        self.assertFalse(captured["rag"])
        self.assertFalse(captured["save"])

    def test_web_ui_defaults_to_web_mode(self) -> None:
        html = (Path("src") / "research_agent" / "web" / "index.html").read_text(encoding="utf-8")
        script = (Path("src") / "research_agent" / "web" / "app.js").read_text(encoding="utf-8")
        styles = (Path("src") / "research_agent" / "web" / "styles.css").read_text(encoding="utf-8")

        self.assertIn('name="mode" value="web" checked', html)
        self.assertNotIn('name="mode" value="auto" checked', html)
        self.assertIn('const DEFAULT_SEARCH_MODE = "web";', script)
        self.assertIn("requested search:", script)
        self.assertIn("actual search:", script)
        self.assertIn("[hidden]", styles)
        self.assertIn("display: none !important", styles)

    def test_fastapi_backend_contract_when_installed(self) -> None:
        if find_spec("fastapi") is None or find_spec("uvicorn") is None:
            self.skipTest("FastAPI and uvicorn are not installed in this environment.")

        import uvicorn
        from research_agent.api import create_app

        with TemporaryDirectory() as tmp_dir:
            port = self._free_port()
            config = uvicorn.Config(
                create_app(Path(tmp_dir)),
                host="127.0.0.1",
                port=port,
                log_level="critical",
            )
            server = uvicorn.Server(config)
            thread = Thread(target=server.run, daemon=True)
            thread.start()
            base_url = f"http://127.0.0.1:{port}"

            try:
                self._wait_for_http(f"{base_url}/api/health")
                with urlopen(f"{base_url}/api/health", timeout=5) as response:
                    health = json.loads(response.read().decode("utf-8"))
                self.assertEqual(health["status"], "ok")

                request = Request(
                    f"{base_url}/api/research",
                    data=json.dumps(
                        {
                            "question": "compare Cursor and Windsurf",
                            "mode": "mock",
                            "llm_mode": "mock",
                            "embedding_mode": "hash",
                            "rag": True,
                            "save": True,
                        }
                    ).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urlopen(request, timeout=10) as response:
                    payload = json.loads(response.read().decode("utf-8"))

                self.assertIn("report", payload)
                self.assertIn("saved_run", payload)
                self.assertIn("Cursor", payload["report"]["markdown"])
                self.assertEqual(payload["report"]["metadata"]["actual_embedding_provider"], "hash")
                self.assertTrue(Path(payload["saved_run"]["trace_path"]).exists())
            finally:
                server.should_exit = True
                thread.join(timeout=5)

    def test_fastapi_request_default_mode_is_web(self) -> None:
        if find_spec("fastapi") is None:
            self.skipTest("FastAPI is not installed in this environment.")

        from research_agent.api import ResearchRequest

        request = ResearchRequest(question="compare youtube and bilibili")
        self.assertEqual(request.mode, "web")

    def mock_pipeline(self) -> ResearchPipeline:
        return ResearchPipeline(search_mode="mock", llm_mode="mock", embedding_mode="hash")

    def _free_port(self) -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            return int(sock.getsockname()[1])

    def _wait_for_http(self, url: str, timeout_seconds: float = 5.0) -> None:
        deadline = time.time() + timeout_seconds
        last_error: Exception | None = None
        while time.time() < deadline:
            try:
                with urlopen(url, timeout=1):
                    return
            except Exception as exc:  # noqa: BLE001 - retry until the server starts.
                last_error = exc
                time.sleep(0.05)
        if last_error:
            raise last_error


if __name__ == "__main__":
    unittest.main()
