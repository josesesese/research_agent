import unittest
from tempfile import TemporaryDirectory

from research_agent.citation_checker import CitationChecker
from research_agent.models import Claim, Evidence
from research_agent.pipeline import ResearchPipeline
from research_agent.searcher import AutoSearcher, MockSearcher, SearchError
from research_agent.storage import ResearchRunStore


class FailingSearcher:
    def search(self, plan):
        raise SearchError("intentional test failure")


class ResearchPipelineTests(unittest.TestCase):
    def test_cursor_windsurf_report_has_sources_and_citations(self) -> None:
        report = ResearchPipeline(search_mode="mock").run("分析 Cursor 和 Windsurf 的区别")

        self.assertTrue(report.sources)
        self.assertTrue(report.documents)
        self.assertTrue(report.evidence)
        self.assertTrue(report.claims)
        self.assertTrue(report.citation_check.passed)
        self.assertIn("Cursor", report.markdown)
        self.assertIn("Windsurf", report.markdown)
        self.assertIn("[S1]", report.markdown)
        self.assertIn("Citation Check", report.markdown)

    def test_citation_checker_flags_missing_evidence(self) -> None:
        checker = CitationChecker()
        result = checker.check(
            claims=[Claim(id="cl_1", topic="Demo", text="A claim", evidence_ids=["missing"])],
            evidence=[Evidence(id="ev_1", source_id="src_1", quote="Quote", note="Note")],
        )

        self.assertFalse(result.passed)
        self.assertTrue(result.issues)

    def test_generic_question_marks_limited_evidence(self) -> None:
        report = ResearchPipeline(search_mode="mock").run("研究一个很冷门的开发工具")

        self.assertTrue(report.citation_check.passed)
        self.assertTrue("资料较少" in report.markdown or "Limited" in report.markdown)

    def test_run_store_writes_report_and_trace(self) -> None:
        report = ResearchPipeline(search_mode="mock").run("分析 Cursor 和 Windsurf 的区别")

        with TemporaryDirectory() as tmp_dir:
            saved = ResearchRunStore(tmp_dir).save(report)

            self.assertTrue(saved.report_path.exists())
            self.assertTrue(saved.trace_path.exists())
            self.assertIn("Research Report", saved.report_path.read_text(encoding="utf-8"))
            self.assertIn("Cursor", saved.trace_path.read_text(encoding="utf-8"))

    def test_auto_searcher_falls_back_to_mock(self) -> None:
        plan = ResearchPipeline(search_mode="mock").planner.plan("分析 Cursor 和 Windsurf 的区别")
        searcher = AutoSearcher(web_searcher=FailingSearcher(), mock_searcher=MockSearcher())

        sources = searcher.search(plan)

        self.assertTrue(sources)
        self.assertTrue(all(source.url.startswith("mock://") for source in sources))


if __name__ == "__main__":
    unittest.main()
