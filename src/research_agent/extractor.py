"""Evidence extraction step."""

from __future__ import annotations

from research_agent.models import Claim, Document, Evidence


class Extractor:
    """Extract deterministic evidence and claims from documents.

    This MVP uses simple rules instead of an LLM so the project can run without
    API keys. The interfaces are designed so an LLM extractor can replace this
    class later.
    """

    def extract(self, documents: list[Document]) -> tuple[list[Evidence], list[Claim]]:
        evidence: list[Evidence] = []
        claims: list[Claim] = []
        documents_by_source = {document.source.id: document for document in documents}

        for index, document in enumerate(documents, start=1):
            quote = self._first_sentence(document.text)
            evidence_id = f"ev_{index:02d}"
            evidence.append(
                Evidence(
                    id=evidence_id,
                    source_id=document.source.id,
                    quote=quote,
                    note=self._note_for_source(document.source.title, quote),
                    confidence=0.72,
                )
            )

        evidence_by_source = {item.source_id: item.id for item in evidence}

        if "src_cursor_overview" in evidence_by_source:
            claims.append(
                Claim(
                    id="cl_cursor_positioning",
                    topic="Cursor positioning",
                    text=(
                        "Cursor 更偏向在熟悉的代码编辑器体验中嵌入 AI，适合希望保留"
                        "现有编辑器习惯、同时获得代码库问答和多文件修改能力的开发者。"
                    ),
                    evidence_ids=[
                        evidence_by_source["src_cursor_overview"],
                        evidence_by_source.get("src_cursor_strengths", evidence_by_source["src_cursor_overview"]),
                    ],
                    confidence=0.76,
                )
            )

        if "src_windsurf_overview" in evidence_by_source:
            claims.append(
                Claim(
                    id="cl_windsurf_positioning",
                    topic="Windsurf positioning",
                    text=(
                        "Windsurf 更强调 agentic coding workspace，让助手围绕任务保持上下文、"
                        "推动从意图到实现的流程。"
                    ),
                    evidence_ids=[
                        evidence_by_source["src_windsurf_overview"],
                        evidence_by_source.get("src_windsurf_strengths", evidence_by_source["src_windsurf_overview"]),
                    ],
                    confidence=0.76,
                )
            )

        if "src_cursor_strengths" in evidence_by_source and "src_windsurf_strengths" in evidence_by_source:
            claims.append(
                Claim(
                    id="cl_workflow_difference",
                    topic="Workflow difference",
                    text=(
                        "两者核心差异可以概括为：Cursor 更像熟悉编辑器中的 AI 加速层，"
                        "Windsurf 更像以 AI 协作为中心的任务工作区。"
                    ),
                    evidence_ids=[
                        evidence_by_source["src_cursor_strengths"],
                        evidence_by_source["src_windsurf_strengths"],
                    ],
                    confidence=0.74,
                )
            )

        if "src_ai_coding_market" in evidence_by_source:
            claims.append(
                Claim(
                    id="cl_common_evaluation_axes",
                    topic="Evaluation axes",
                    text=(
                        "评估 AI coding tools 时，应同时比较编辑器熟悉度、自动化程度、"
                        "代码库上下文、协作治理、价格和模型选择。"
                    ),
                    evidence_ids=[evidence_by_source["src_ai_coding_market"]],
                    confidence=0.72,
                )
            )

        web_claims = self._extract_web_claims(documents_by_source, evidence_by_source)
        existing_claim_ids = {claim.id for claim in claims}
        for claim in web_claims:
            if claim.id not in existing_claim_ids:
                claims.append(claim)

        if not claims and evidence:
            claims.append(
                Claim(
                    id="cl_limited_evidence",
                    topic="Limited evidence",
                    text="当前 Mock 资料较少，只能给出研究方法层面的初步结论，不能替代真实网页调研。",
                    evidence_ids=[evidence[0].id],
                    confidence=0.55,
                )
            )

        return evidence, claims

    def _extract_web_claims(
        self,
        documents_by_source: dict[str, Document],
        evidence_by_source: dict[str, str],
    ) -> list[Claim]:
        cursor_evidence: list[str] = []
        windsurf_evidence: list[str] = []
        pricing_evidence: list[str] = []

        for source_id, document in documents_by_source.items():
            haystack = f"{document.source.title} {document.source.snippet} {document.text}".lower()
            evidence_id = evidence_by_source.get(source_id)
            if not evidence_id:
                continue

            if "cursor" in haystack:
                cursor_evidence.append(evidence_id)
            if "windsurf" in haystack or "codeium" in haystack:
                windsurf_evidence.append(evidence_id)
            if "pricing" in haystack or "price" in haystack or "plan" in haystack:
                pricing_evidence.append(evidence_id)

        claims: list[Claim] = []
        if cursor_evidence:
            claims.append(
                Claim(
                    id="cl_web_cursor_evidence",
                    topic="Cursor evidence",
                    text="检索到的网页资料包含 Cursor 相关信息，可作为后续产品定位和功能对比的证据基础。",
                    evidence_ids=cursor_evidence[:2],
                    confidence=0.62,
                )
            )

        if windsurf_evidence:
            claims.append(
                Claim(
                    id="cl_web_windsurf_evidence",
                    topic="Windsurf evidence",
                    text="检索到的网页资料包含 Windsurf 或 Codeium/Windsurf 相关信息，可用于分析其 AI coding workflow。",
                    evidence_ids=windsurf_evidence[:2],
                    confidence=0.62,
                )
            )

        if cursor_evidence and windsurf_evidence:
            claims.append(
                Claim(
                    id="cl_web_comparison_basis",
                    topic="Comparison basis",
                    text="当前资料同时覆盖 Cursor 和 Windsurf，报告可以围绕产品定位、工作流、适用人群和风险展开对比。",
                    evidence_ids=(cursor_evidence[:1] + windsurf_evidence[:1]),
                    confidence=0.6,
                )
            )

        if pricing_evidence:
            claims.append(
                Claim(
                    id="cl_web_pricing_needs_verification",
                    topic="Pricing verification",
                    text="部分检索资料涉及价格或套餐信息，这类信息变化较快，最终报告需要以官方页面或最新资料复核。",
                    evidence_ids=pricing_evidence[:2],
                    confidence=0.58,
                )
            )

        return claims

    def _first_sentence(self, text: str) -> str:
        separators = [". ", "。", "! ", "? "]
        best = text.strip()
        for separator in separators:
            if separator in best:
                return best.split(separator, 1)[0].strip() + separator.strip()
        return best[:240].strip()

    def _note_for_source(self, title: str, quote: str) -> str:
        return f"Extracted from {title}: {quote[:120]}"
