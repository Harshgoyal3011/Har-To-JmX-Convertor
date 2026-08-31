"""Build the JSON summary the web UI renders from an EngineResult."""

from __future__ import annotations

import re
from typing import Any

from har2jmx.engine import EngineResult

_TOKENISH = re.compile(r"token|session|auth|jwt|sid", re.IGNORECASE)


def _mask(value: str) -> str:
    v = str(value)
    if len(v) > 10:
        return f"{v[:4]}…{v[-3:]}"
    return v


def _suggestion(reason: str) -> str:
    if "not " in reason and "captured" in reason:
        return ("Capture the response that issues this value (re-record with response bodies enabled), "
                "then add a Boundary/Regex Extractor on it and reference the value as ${…}.")
    return ("Confirm whether the server issues this value; if so, add an extractor on its producing "
            "response and reference it as ${…} instead of the recorded literal.")


def build_manual_correlations(result: EngineResult) -> list[dict[str, Any]]:
    """Dynamic values the engine could not auto-correlate — the list a performance engineer must wire
    up by hand before running at load (e.g. a token whose issuing response was not captured)."""
    cap = result.capture
    items: list[dict[str, Any]] = []
    for v in result.classification.needs_correlation():
        used_in: list[str] = []
        seen: set[str] = set()
        for i in v.consumers:
            if 0 <= i < len(cap.requests):
                rq = cap.requests[i]
                label = f"{rq.context.transaction or 'flow'} — {rq.label()}"
                if label not in seen:
                    seen.add(label)
                    used_in.append(label)
        field = v.entity_field or (v.source.split(":")[-1] if ":" in v.source else v.source) or "value"
        items.append({
            "field": field,
            "value": _mask(v.value),
            "reason": v.reason,
            "usedIn": used_in[:8],
            "suggestion": _suggestion(v.reason),
        })
    return items


def _derived_auth_list(result: EngineResult) -> list[str]:
    # If no standard mechanism matched but a token-like value is correlated, report it (evidence-backed).
    if any(_TOKENISH.search(c.variable) for c in result.correlations):
        return ["Token session"]
    return []


def _derived_auth(result: EngineResult) -> str | None:
    d = _derived_auth_list(result)
    return d[0] if d else None


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
            "primary": result.auth.primary or _derived_auth(result),
            "mechanisms": [d.name for d in result.auth.mechanisms] or _derived_auth_list(result),
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
        "manualCorrelations": build_manual_correlations(result),
        "downloads": downloads,
    }
