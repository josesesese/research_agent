## Runtime Notes

- Gemini report generation failed, so the system returned the deterministic template report.
- Failure reason: gemini_api_error: GEMINI_API_KEY is not set. Set GEMINI_API_KEY for Gemini report synthesis, or use --llm-mode mock for offline tests.

# Research Report: compare youtube and bilibili

> MVP note: this report may use mock or live web sources depending on the selected search mode. Verify fast-changing facts before external use.

## Executive Summary

- 当前 Mock 资料较少，只能给出研究方法层面的初步结论，不能替代真实网页调研。 [S1]

## Research Plan

- **这个问题需要哪些背景信息？** 先明确研究对象和范围。
- **有哪些可验证证据支持主要结论？** 确保报告不是凭空总结。
- **当前资料有哪些不足或不确定性？** 在资料不足时主动标注限制。

## Comparison Snapshot

| Dimension | Finding |
| --- | --- |
| Evidence quality | Limited in MVP mock mode |
| Recommendation | Add real search before treating results as factual |

## Key Claims

- **Limited evidence:** 当前 Mock 资料较少，只能给出研究方法层面的初步结论，不能替代真实网页调研。 [S1]

## Evidence Extracts

- [S1] A reliable research report separates evidence from interpretation.

## RAG Context

- rank=1, score=0.0845, [S1] A reliable research report separates evidence from interpretation. It should list sources, quote or paraphrase relevant evidence, and mark uncertainty when the available sources are weak, stale, or incomplete.

## Gaps And Next Steps

- Improve live search ranking, source diversity, and official-source filtering.
- Verify live pricing, product names, policy details, and publication dates before using the report externally.
- Add an LLM extractor later for richer claim clustering and contradiction handling.

## Sources

- [S1] General research method note (mock, 2026-01-01) - mock://research/general-method

## Citation Check

Passed: every claim has at least one valid evidence reference.
