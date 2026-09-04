"""Milestone 12 — engine orchestration, metrics & final review.

The pure core: `analyze(har)` runs the whole reasoning pipeline (M1–M11) and returns an
`EngineResult` with the decisions plus **measured** quality metrics (never fabricated; proxy/estimated
values are labelled). This is the single stable entry point every adapter (CLI, web, future SaaS)
calls — no I/O, no globals.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from har2jmx.classify import ClassificationResult, classify_capture, classify_values
from har2jmx.correlate import CorrelationDecision, build_correlations
from har2jmx.entities import RelationshipModel, discover_relationships
from har2jmx.ir.build import build_capture
from har2jmx.ir.normalized import NormalizedCapture
from har2jmx.lineage import build_lineage
from har2jmx.parameterize import ParameterizationPlan, build_parameterization
from har2jmx.understand import ApplicationProfile, AuthProfile, detect_application, detect_auth
from har2jmx.validate import ExtractorCheck, ReplayReport, validate_replay, verify_extractors
from har2jmx.workflow import Transaction, discover_transactions


@dataclass
class EngineResult:
    capture: NormalizedCapture
    application: ApplicationProfile
    auth: AuthProfile
    transactions: list[Transaction]
    entities_model: RelationshipModel
    classification: ClassificationResult
    correlations: list[CorrelationDecision]
    parameterization: ParameterizationPlan
    replay: ReplayReport
    extractor_checks: list[ExtractorCheck] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)


def _metrics(res: EngineResult) -> dict[str, Any]:
    reqs = res.capture.requests
    total = len(reqs)
    business = [r for r in reqs if not r.classification.excluded]
    excluded = total - len(business)
    corr = res.correlations
    datasets = res.parameterization.datasets
    from har2jmx.validate import ExtractorStatus
    checks = res.extractor_checks
    unresolved = sum(1 for c in checks if c.status == ExtractorStatus.UNRESOLVED)
    return {
        "requests": {
            "total": total,
            "business": len(business),
            "excluded": excluded,
            "excluded_pct": round(100 * excluded / total, 1) if total else 0.0,
        },
        "transactions": {
            "count": len(res.transactions),
            "avg_requests_per_transaction": round(total / len(res.transactions), 2) if res.transactions else 0.0,
        },
        "entities": {
            "count": len(res.entities_model.entities),
            "relationships": len(res.entities_model.relationships),
        },
        "correlation": {
            "count": len(corr),
            "high_confidence": sum(1 for c in corr if c.confidence == "High"),
            "coverage_per_business_request": round(len(corr) / max(len(business), 1), 2),
            "verified_unique": sum(1 for c in checks if c.status == ExtractorStatus.UNIQUE),
            "refined": sum(1 for c in checks if c.status == ExtractorStatus.AMBIGUOUS_REFINED),
            "unresolved": unresolved,
        },
        "parameterization": {
            "datasets": len(datasets),
            "columns": sum(len(d.columns) for d in datasets),
            "rows": sum(d.row_count for d in datasets),
        },
        "replay_readiness": res.replay.score,
        "manual_review_items": len(res.replay.issues()) + len(res.classification.unknowns()) + unresolved,
        "_estimated": [
            "correlation.high_confidence is a precision proxy (no external ground truth)",
            "manual_review_items counts flagged findings + ambiguous values",
        ],
    }


def analyze(har: bytes | dict) -> EngineResult:
    """Run the full HAR → decisions reasoning pipeline and return an EngineResult."""
    cap = build_capture(har)
    classify_capture(cap)                     # M2: tag roles / exclusions

    application = detect_application(cap)       # M3
    auth = detect_auth(cap)
    transactions = discover_transactions(cap)   # M4
    model = discover_relationships(cap)         # M5 + M6 (entities + relationships + aligned rows)
    lineage = build_lineage(cap)                # M7
    classification = classify_values(cap, lineage)          # M8
    correlations = build_correlations(cap, classification, lineage)   # M9
    parameterization = build_parameterization(cap, classification, model, lineage)  # M10
    replay = validate_replay(cap, correlations, parameterization, classification, lineage)  # M11
    extractor_checks = verify_extractors(cap, correlations)   # resolve each extractor against its response

    result = EngineResult(
        capture=cap, application=application, auth=auth, transactions=transactions,
        entities_model=model, classification=classification, correlations=correlations,
        parameterization=parameterization, replay=replay, extractor_checks=extractor_checks,
    )
    result.metrics = _metrics(result)           # M12
    return result
