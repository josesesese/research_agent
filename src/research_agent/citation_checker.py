"""Citation validation step."""

from __future__ import annotations

from research_agent.models import CitationCheckResult, CitationIssue, Claim, Evidence


class CitationChecker:
    """Check that each claim has at least one valid evidence reference."""

    def check(self, claims: list[Claim], evidence: list[Evidence]) -> CitationCheckResult:
        evidence_ids = {item.id for item in evidence}
        issues: list[CitationIssue] = []

        for claim in claims:
            if not claim.evidence_ids:
                issues.append(CitationIssue(claim_id=claim.id, message="Claim has no evidence references."))
                continue

            missing = [evidence_id for evidence_id in claim.evidence_ids if evidence_id not in evidence_ids]
            if missing:
                issues.append(
                    CitationIssue(
                        claim_id=claim.id,
                        message=f"Claim references missing evidence ids: {', '.join(missing)}.",
                    )
                )

        return CitationCheckResult(passed=not issues, issues=issues)
