"""Build the JSON summary the web UI renders from an EngineResult."""

from __future__ import annotations

from typing import Any

from har2jmx.engine import EngineResult


def _mask(value: str) -> str:
    v = str(value)
    if len(v) > 10:
        return f"{v[:4]}…{v[-3:]}"
    return v


def build_web_summary(result: EngineResult, result_id: str, downloads: dict[str, Any]) -> dict[str, Any]:
    cap = result.capture
    m = result.metrics
    app = result.application

    def txn_of(idx: int) -> str:
        return cap.requests[idx].context.transaction

    reqs = m["requests"]
    return {
        "id": result_id,
        "requests": {
            "total": reqs["total"], "business": reqs["business"],
            "excluded": reqs["excluded"], "excludedPct": reqs["excluded_pct"],
        },
        "metrics": {
            "transactions": m["transactions"]["count"],
            "correlations": m["correlation"]["count"],
            "parameters": m["parameterization"]["columns"],
            "datasets": m["parameterization"]["datasets"],
            "entities": m["entities"]["count"],
            "replayReadiness": m["replay_readiness"],
            "manualReview": m["manual_review_items"],
        },
        "application": {
            "apiStyles": [d.name for d in app.api_styles],
            "servers": [d.name for d in app.server_stack],
            "spa": [d.name for d in app.spa_frameworks],
            "enterprise": [d.name for d in app.enterprise_platforms],
        },
        "auth": {
            "primary": result.auth.primary,
            "mechanisms": [d.name for d in result.auth.mechanisms],
            "tokenRefresh": result.auth.token_refresh,
        },
        "transactions": [
            {
                "name": t.name,
                "category": t.category,
                "requests": len([i for i in t.request_indices if not cap.requests[i].classification.excluded]),
            }
            for t in result.transactions
        ],
        "correlations": [
            {
                "variable": c.variable,
                "value": _mask(c.value),
                "extractor": c.extractor.value,
                "expression": c.expression,
                "confidence": c.confidence,
                "reason": c.reason,
                "consumers": len(c.consumers),
                "producedIn": txn_of(c.producer_index),
                "entity": c.entity,
            }
            for c in result.correlations
        ],
        "parameters": [
            {
                "dataset": d.name,
                "columns": [col.name for col in d.columns],
                "rows": d.row_count,
                "source": d.source,
                "reason": d.reason,
            }
            for d in result.parameterization.datasets
        ],
        "replay": {
            "passed": result.replay.passed,
            "score": result.replay.score,
            "findings": [
                {"check": f.check, "severity": f.severity, "passed": f.passed, "detail": f.detail}
                for f in result.replay.findings
            ],
        },
        "excluded": [
            {
                "label": r.label(),
                "role": r.classification.role.value,
                "reason": r.classification.exclusion_reason,
            }
            for r in cap.requests if r.classification.excluded
        ][:14],
        "downloads": downloads,
    }
