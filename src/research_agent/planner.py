"""Research planning step."""

from __future__ import annotations

from research_agent.models import ResearchPlan, ResearchQuestion, ResearchSubQuestion


class Planner:
    """Create a small, deterministic research plan for the MVP."""

    def plan(self, question_text: str) -> ResearchPlan:
        question = ResearchQuestion(text=question_text.strip())
        normalized = question.text.lower()

        if "cursor" in normalized and "windsurf" in normalized:
            sub_questions = [
                ResearchSubQuestion(
                    id="sq_positioning",
                    text="Cursor 和 Windsurf 的产品定位分别是什么？",
                    rationale="产品定位决定最终报告的主线。",
                ),
                ResearchSubQuestion(
                    id="sq_workflow",
                    text="两者在开发工作流和 AI 交互方式上有什么差异？",
                    rationale="这是 AI coding tool 对比中最重要的使用体验维度。",
                ),
                ResearchSubQuestion(
                    id="sq_strengths",
                    text="两者各自更适合哪些用户或团队？",
                    rationale="报告需要给出可行动的选择建议。",
                ),
                ResearchSubQuestion(
                    id="sq_risks",
                    text="使用这类工具时有哪些共同风险或限制？",
                    rationale="避免只写优点，体现研究完整性。",
                ),
            ]
            search_queries = [
                "Cursor AI code editor overview",
                "Windsurf AI coding agent overview",
                "Cursor vs Windsurf comparison",
                "AI coding tools pricing governance context comparison",
            ]
        else:
            sub_questions = [
                ResearchSubQuestion(
                    id="sq_context",
                    text="这个问题需要哪些背景信息？",
                    rationale="先明确研究对象和范围。",
                ),
                ResearchSubQuestion(
                    id="sq_evidence",
                    text="有哪些可验证证据支持主要结论？",
                    rationale="确保报告不是凭空总结。",
                ),
                ResearchSubQuestion(
                    id="sq_uncertainty",
                    text="当前资料有哪些不足或不确定性？",
                    rationale="在资料不足时主动标注限制。",
                ),
            ]
            search_queries = [question.text]

        return ResearchPlan(
            question=question,
            sub_questions=sub_questions,
            search_queries=search_queries,
        )
