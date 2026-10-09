"""Build the JSON summary the web UI renders from an EngineResult."""

from __future__ import annotations

import re
from typing import Any
from xml.etree import ElementTree as ET

from har2jmx.correlate import ExtractorType, RejectionKind
from har2jmx.engine import EngineResult

_TOKENISH = re.compile(r"token|session|auth|jwt|sid", re.IGNORECASE)
_EXTRACTOR_NAME_RE = re.compile(
    r'(?:JSONPostProcessor\.referenceNames|RegexExtractor\.refname)">([^<]+)<'
)


def _extractor_names_from_jmx(jmx_xml: str | bytes | None) -> set[str] | None:
    """Names of extractors that actually shipped in the JMX — the product source of truth."""
    if jmx_xml is None:
        return None
    x = jmx_xml.decode("utf-8") if isinstance(jmx_xml, (bytes, bytearray)) else jmx_xml
    return set(_EXTRACTOR_NAME_RE.findall(x)) | set(re.findall(r'referenceNames">([^<]+)<', x))


def _correlation_implementation(result: EngineResult, jmx_xml: str | bytes) -> dict[str, dict]:
    """Verify producer/extractor and consumer references in the final emitted plan.

    Assertions, labels and processor code do not count as request consumers.
    Redirect Location and CookieManager remain separate execution mechanisms.
    This inspection never changes decisions or generated requests.
    """
    from har2jmx.emit.jmx import _replayable_header
    from har2jmx.emit.redirects import redirect_execution

    root = ET.fromstring(jmx_xml)
    redirects = redirect_execution(result, _replayable_header)
    indices = [index for transaction in result.transactions for index in transaction.request_indices
               if not result.capture.requests[index].classification.excluded
               and index not in redirects.automatic_targets]
    samplers = list(root.iter("HTTPSamplerProxy"))
    parents = {child: parent for parent in root.iter() for child in parent}

    def adjacent_tree(node):
        siblings = list(parents[node])
        position = siblings.index(node) + 1
        return siblings[position] if position < len(siblings) and siblings[position].tag == "hashTree" else ET.Element("hashTree")

    def enabled(node):
        return node.get("enabled", "true") != "false"

    def refs(text):
        return set(re.findall(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", text or ""))

    def header_refs(node):
        return set().union(*(refs(p.text) for p in node.findall(".//stringProp[@name='Header.value']")))

    global_refs = set()
    for manager in root.iter("HeaderManager"):
        parent = manager
        while parent in parents and parent.tag != "hashTree":
            parent = parents[parent]
        siblings = list(parents.get(parent, ET.Element("empty")))
        previous = siblings[siblings.index(parent) - 1] if parent in siblings and siblings.index(parent) else None
        if enabled(manager) and (previous is None or previous.tag != "HTTPSamplerProxy"):
            global_refs.update(header_refs(manager))

    sources = {}; consumers = {}
    for index, sampler in zip(indices, samplers):
        if not enabled(sampler):
            continue
        tree = adjacent_tree(sampler)
        sources[index] = {p.text or "" for node in tree
                          if node.tag in {"JSONPostProcessor", "RegexExtractor"} and enabled(node)
                          for p in node if p.get("name") in {"JSONPostProcessor.referenceNames", "RegexExtractor.refname"}}
        consumer_refs = set(global_refs)
        for p in sampler.iter("stringProp"):
            if p.get("name") in {"Argument.value", "HTTPSampler.path"}:
                consumer_refs.update(refs(p.text))
        for manager in tree.iter("HeaderManager"):
            if enabled(manager):
                consumer_refs.update(header_refs(manager))
        consumers[index] = consumer_refs

    cookie_manager = any(enabled(node) for node in root.iter("CookieManager"))
    audit = {}
    for correlation in result.correlations:
        if correlation.extractor == ExtractorType.COOKIE_MANAGER:
            implemented = cookie_manager and bool(correlation.consumers)
            bound = list(correlation.consumers) if implemented else []
            mechanism = "cookie_manager"
        else:
            implemented = correlation.variable in sources.get(correlation.producer_index, set())
            bound = [index for index in correlation.consumers
                     if index > correlation.producer_index and correlation.variable in consumers.get(index, set())]
            mechanism = "extractor"
        complete = implemented and bool(bound) and set(bound) == set(correlation.consumers)
        if not implemented:
            reason = "The generated JMX has no enabled extractor on the producing request." if mechanism == "extractor" else "The generated JMX has no enabled Cookie Manager."
        elif not bound:
            reason = "An extractor was generated, but its variable is not used by any approved downstream request."
        elif not complete:
            reason = "The generated JMX uses this variable in only some approved downstream requests."
        else:
            reason = "Producer and downstream request bindings are present in the generated JMX."
        audit[correlation.variable] = {"implemented": complete, "extractorPresent": implemented,
                                      "boundConsumers": bound, "expectedConsumers": correlation.consumers,
                                      "mechanism": mechanism, "reason": reason}
    return audit


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


def _used_in(cap, consumers) -> list[str]:
    used_in: list[str] = []
    seen: set[str] = set()
    for i in consumers:
        if 0 <= i < len(cap.requests):
            rq = cap.requests[i]
            label = f"{rq.context.transaction or 'flow'} — {rq.label()}"
            if label not in seen:
                seen.add(label)
                used_in.append(label)
    return used_in[:8]


def build_manual_correlations(result: EngineResult, jmx_xml: str | bytes | None = None) -> list[dict[str, Any]]:
    """Dynamic values the engine could not auto-correlate — the list a performance engineer must wire
    up by hand before running at load. Two sources: values with no captured producer at all
    (``needs_correlation``), and correlations whose extractor could not be verified against the
    capture (``extractor_checks`` UNRESOLVED) — the latter would otherwise ship as a false green."""
    cap = result.capture
    items: list[dict[str, Any]] = []
    listed: set[str] = set()
    for v in result.classification.needs_correlation():
        field = v.entity_field or (v.source.split(":")[-1] if ":" in v.source else v.source) or "value"
        items.append({
            "field": field,
            "value": _mask(v.value),
            "reason": v.reason,
            "usedIn": _used_in(cap, v.consumers),
            "suggestion": _suggestion(v.reason),
        })
        listed.add(v.value)
    # extractors that were decided but did not resolve against the producing response
    for chk in result.extractor_checks:
        if chk.ok or chk.value in listed:
            continue
        listed.add(chk.value)
        items.append({
            "field": chk.variable,
            "value": _mask(chk.value),
            "reason": chk.reason,
            "usedIn": _used_in(cap, chk.consumers),
            "suggestion": chk.suggestion or _suggestion(chk.reason),
        })
    if jmx_xml is not None:
        audit = _correlation_implementation(result, jmx_xml)
        listed_fields = {item["field"] for item in items}
        for correlation in result.correlations:
            implementation = audit[correlation.variable]
            if implementation["implemented"] or correlation.variable in listed_fields:
                continue
            items.append({"field": correlation.variable, "value": _mask(correlation.value),
                          "reason": implementation["reason"], "usedIn": _used_in(cap, correlation.consumers),
                          "suggestion": "Review the producer extractor and replace the intended downstream request values with "
                                        f"${{{correlation.variable}}} using the required request encoding."})
    return items


def assess_capture_quality(cap) -> dict[str, Any]:
    """Up-front signal on capture completeness: correlation can only be as good as the capture. A HAR
    recorded without response bodies (a common devtools setting) hides the values that must be
    correlated — so we surface that before the user trusts the output."""
    business = [r for r in cap.requests if not r.classification.excluded]
    total = len(business)
    with_body = sum(1 for r in business
                    if r.response.body.json is not None or (r.response.body.raw or "").strip())
    with_timing = sum(1 for r in business if (r.context.started or "").strip())
    coverage = round(100 * with_body / total) if total else 100

    def _is_error(r) -> bool:
        try:
            return int(str(r.status)) >= 400
        except (TypeError, ValueError):
            return False
    errors = sum(1 for r in business if _is_error(r))
    error_pct = round(100 * errors / total) if total else 0
    # A capture where most responses were 4xx/5xx recorded a broken session: the created ids never
    # existed, so nothing correlates and every sampler will fail the response assertion at run time.
    error_dominated = bool(total) and error_pct >= 50

    return {
        "businessResponses": total,
        "withBody": with_body,
        "emptyBodies": total - with_body,
        "withTiming": with_timing,
        "bodyCoveragePct": coverage,
        "errorResponses": errors,
        "errorPct": error_pct,
        "errorDominated": error_dominated,
        # degraded when responses carry no body (correlation is blind) OR most were errors (broken session)
        "degraded": (bool(total) and coverage < 75) or error_dominated,
    }


def _derived_auth_list(result: EngineResult) -> list[str]:
    # If no standard mechanism matched but a token-like value is correlated, report it (evidence-backed).
    if any(_TOKENISH.search(c.variable) for c in result.correlations):
        return ["Token session"]
    return []


def _derived_auth(result: EngineResult) -> str | None:
    d = _derived_auth_list(result)
    return d[0] if d else None


def build_web_summary(result: EngineResult, result_id: str, downloads: dict[str, Any],
                      jmx_xml: str | bytes | None = None) -> dict[str, Any]:
    cap = result.capture
    m = result.metrics
    app = result.application

    def txn_of(idx: int) -> str:
        return cap.requests[idx].context.transaction

    # Show ONLY the correlations the emitter actually put in the script. An extractor that could not be
    # verified against the capture is dropped from the plan (the value ships as a literal and is listed
    # under "needs manual correlation") — so it must NOT also appear in the Correlations table, or the UI
    # claims a correlation the script does not contain. Cookie-manager correlations have no extractor to
    # verify and are always emitted; UNIQUE/AMBIGUOUS_REFINED are emitted; UNRESOLVED are not.
    _check_by_var = {chk.variable: chk for chk in result.extractor_checks}

    def _emitted(c) -> bool:
        chk = _check_by_var.get(c.variable)
        return chk is None or chk.ok

    def _shown_expr(c) -> str:
        chk = _check_by_var.get(c.variable)
        return chk.refined_expression if (chk and chk.refined_expression) else c.expression

    shown_correlations = [c for c in result.correlations if _emitted(c)]
    implementation = _correlation_implementation(result, jmx_xml) if jmx_xml is not None else None
    if implementation is not None:
        shown_correlations = [
            c for c in shown_correlations
            if implementation[c.variable]["implemented"]
        ]

    reqs = m["requests"]
    return {
        "id": result_id,
        "requests": {
            "total": reqs["total"], "business": reqs["business"],
            "excluded": reqs["excluded"], "excludedPct": reqs["excluded_pct"],
        },
        "metrics": {
            "transactions": m["transactions"]["count"],
            "correlations": len(shown_correlations),   # required/emitted only — not discovery candidates
            "correlationCandidates": len(getattr(result.correlation_audit, "candidates", []) or []),
            # count the parameters/datasets actually in the plan (usage-aware pruning may have dropped
            # unreferenced columns during emission) — keep this in step with the CSV and the list below
            "parameters": sum(len(d.columns) for d in result.parameterization.datasets),
            "datasets": len(result.parameterization.datasets),
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
                "expression": _shown_expr(c),
                "confidence": c.confidence,
                "reason": c.reason,
                "consumers": len(implementation[c.variable]["boundConsumers"]) if implementation is not None else len(c.consumers),
                "implementation": implementation[c.variable] if implementation is not None else None,
                "producedIn": txn_of(c.producer_index),
                "entity": c.entity,
            }
            for c in shown_correlations
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
        "parameterizationReview": [
            {
                "value": it.value[:24],
                "intent": it.intent,
                "reason": it.reason,
                "field": it.logical_field,
                "slots": it.slots,
            }
            for it in result.parameterization.review[:24]
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
        "manualCorrelations": build_manual_correlations(result, jmx_xml),
        "correlationImplementation": implementation,
        "correlationAudit": {
            "candidates": len(result.correlation_audit.candidates),
            "required": len(shown_correlations),
            "superseded": result.correlation_audit.count(RejectionKind.SUPERSEDED),
            "rejectedConfiguration": result.correlation_audit.count(RejectionKind.CONFIGURATION),
            "rejectedProtocol": result.correlation_audit.count(RejectionKind.PROTOCOL_METADATA),
            "rejectedMasterData": result.correlation_audit.count(RejectionKind.MASTER_DATA),
            "noConsumer": result.correlation_audit.count(RejectionKind.NO_CONSUMER),
            "review": result.correlation_audit.count(RejectionKind.REVIEW),
            "notRequired": result.correlation_audit.count(RejectionKind.NOT_REQUIRED),
        },
        "captureQuality": assess_capture_quality(cap),
        "downloads": downloads,
    }
