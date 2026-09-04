"""Extractor self-check — resolve every emitted extractor against its captured response.

The correlation engine (M9) decides *which* value to extract and picks an expression from the field
name (``$..orderId``). Nothing, until here, confirms that expression actually resolves to the intended
value in the producing response. It usually does — but two real cases silently break at load:

* **Ambiguous recursive JSONPath.** ``$..orderId`` with ``match_number=1`` returns the *first* node
  named ``orderId`` anywhere in the body. When a create-response echoes the created object **and** a
  list of prior orders, match #1 can be the wrong one. The lineage walker collapses list indices, so
  the decision layer can't see the ambiguity.
* **A pattern that no longer matches.** A regex/JSON path that resolves to nothing (or to a different
  value) ships as a ``${var}`` that falls back to ``NOT_FOUND`` at run time — a false green.

This module resolves each non-cookie extractor against the real captured response and classifies it:

* ``UNIQUE`` — resolves to exactly the recorded value; ship as-is.
* ``AMBIGUOUS_REFINED`` — the recursive path is ambiguous but the value sits at a stable, index-free
  object path; pin the extractor to that concrete path (``$.order.orderId``).
* ``UNRESOLVED`` — cannot be resolved to a stable extractor (value absent, wrong match, or only present
  inside a per-run list). The emitter drops the auto-extractor and the value is escalated to the
  manual-review report instead of shipping a false green.

Pure analysis over the normalized capture; no I/O, stdlib + the pipeline's own helpers only.
"""

from __future__ import annotations

import json as _json
import re as _re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from har2jmx.correlate import CorrelationDecision, ExtractorType
from har2jmx.ir.normalized import NormalizedCapture, NormalizedRequest
from har2jmx.lineage.graph import _norm, _walk_json   # reuse the exact traversal + equality the pipeline uses

_MAX_DEPTH = 6
_MAX_LIST = 25


class ExtractorStatus(str, Enum):
    UNIQUE = "unique"                     # resolves to exactly the recorded value
    AMBIGUOUS_REFINED = "ambiguous_refined"   # ambiguous $..leaf pinned to a concrete stable path
    UNRESOLVED = "unresolved"             # cannot be resolved to a stable extractor → escalate


@dataclass
class ExtractorCheck:
    variable: str
    value: str
    producer_index: int
    extractor: ExtractorType
    status: ExtractorStatus
    expression: str = ""                  # the original expression
    refined_expression: str = ""          # concrete path when AMBIGUOUS_REFINED (else "")
    reason: str = ""
    suggestion: str = ""
    consumers: list[int] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status in (ExtractorStatus.UNIQUE, ExtractorStatus.AMBIGUOUS_REFINED)


def _scalar(v: Any) -> bool:
    return isinstance(v, (str, int, float)) and not isinstance(v, bool)


def _walk_json_indexed(obj: Any, prefix: str, out: list[tuple[str, Any]], depth: int = 0) -> None:
    """Like lineage's ``_walk_json`` but *keeps* list indices in the path (``orders[3].orderId``), so
    the exact node holding a value — and whether it lives inside a list — can be recovered."""
    if depth > _MAX_DEPTH:
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            kp = f"{prefix}.{k}" if prefix else str(k)
            if _scalar(v):
                out.append((kp, v))
            elif isinstance(v, (dict, list)):
                _walk_json_indexed(v, kp, out, depth + 1)
    elif isinstance(obj, list):
        for i, item in enumerate(obj[:_MAX_LIST]):
            ip = f"{prefix}[{i}]"
            if _scalar(item):
                out.append((ip, item))
            elif isinstance(item, (dict, list)):
                _walk_json_indexed(item, ip, out, depth + 1)


def _producer_body_json(req: NormalizedRequest) -> Any:
    if req.response.body.json is not None:
        return req.response.body.json
    raw = (req.response.body.raw or "").strip()
    if raw:
        try:
            return _json.loads(raw)
        except (ValueError, TypeError):
            return None
    return None


def _leaf_of(expression: str) -> str:
    e = expression.strip()
    if e.startswith("$.."):
        return e[3:]
    return e.split(".")[-1] or e


def _json_suggestion(leaf: str) -> str:
    return (f"'{leaf}' could not be pinned to a stable JSONPath — it appears in a per-run list. "
            "Select it with a JSONPath filter on a stable sibling (e.g. $.orders[?(@.status=='NEW')]."
            f"{leaf}), or add a Boundary Extractor anchored on the field label, and reference it as ${{…}}.")


def _regex_suggestion() -> str:
    return ("The recorded extractor pattern did not match the captured response, so it would fall back "
            "to NOT_FOUND at run time. Confirm the value is server-issued and re-anchor the extractor on "
            "its producing response (Boundary/Regex Extractor), then reference it as ${…}.")


def _headers_text(req: NormalizedRequest) -> str:
    """Approximate JMeter's 'Response Headers' field, which useHeaders extractors match against."""
    lines: list[str] = [f"{n}: {v}" for n, v in req.response.headers if v]
    lines += [f"Set-Cookie: {n}={v}" for n, v in req.response.set_cookies if v]
    loc = req.response.redirect_location
    if loc and not any(n.lower() == "location" for n, _ in req.response.headers):
        lines.append(f"Location: {loc}")
    return "\n".join(lines)


def _check_json(dec: CorrelationDecision, producer: NormalizedRequest) -> ExtractorCheck:
    leaf = _leaf_of(dec.expression)
    target = _norm(dec.value)
    body = _producer_body_json(producer)

    def make(status: ExtractorStatus, refined: str = "", reason: str = "", suggestion: str = "") -> ExtractorCheck:
        return ExtractorCheck(variable=dec.variable, value=dec.value, producer_index=dec.producer_index,
                              extractor=dec.extractor, status=status, expression=dec.expression,
                              refined_expression=refined, reason=reason, suggestion=suggestion,
                              consumers=list(dec.consumers))

    if body is None:
        return make(ExtractorStatus.UNRESOLVED,
                    reason=(f"the producing response body was not captured/parseable, so {dec.expression} "
                            "cannot be verified and would fall back to NOT_FOUND at run time."),
                    suggestion=("Re-record the capture with response bodies enabled so this value's issuing "
                                "response is present, then it can be correlated automatically."))

    # collapsed walk = what JMeter's `$..leaf` sees (every node named `leaf`, in document order)
    collapsed: list[tuple[str, Any]] = []
    _walk_json(body, "", collapsed)
    named = [(kp, v) for kp, v in collapsed if kp.split(".")[-1] == leaf]

    if not named:
        return make(ExtractorStatus.UNRESOLVED,
                    reason=(f"{dec.expression} does not resolve in the producing response "
                            f"(no field '{leaf}' present) — it would fall back to NOT_FOUND at run time."),
                    suggestion=_json_suggestion(leaf))

    if len(named) == 1:
        if _norm(named[0][1]) == target:
            return make(ExtractorStatus.UNIQUE)
        return make(ExtractorStatus.UNRESOLVED,
                    reason=(f"{dec.expression} resolves to a different value than recorded in the producing "
                            f"response — the correlation would replay the wrong value."),
                    suggestion=_json_suggestion(leaf))

    # ambiguous: several nodes named `leaf`. Find where the recorded value actually sits.
    indexed: list[tuple[str, Any]] = []
    _walk_json_indexed(body, "", indexed)
    hits = [kp for kp, v in indexed if kp.split(".")[-1] == leaf and _norm(v) == target]
    stable = [kp for kp in hits if "[" not in kp]           # index-free path = stable across runs
    if len(stable) == 1:
        return make(ExtractorStatus.AMBIGUOUS_REFINED, refined=f"$.{stable[0]}",
                    reason=(f"$..{leaf} is ambiguous (matches {len(named)} nodes); pinned to the concrete "
                            f"path $.{stable[0]} so the correct value is extracted under load."))
    # value lives inside a per-run list (or is itself duplicated) → no stable static path
    return make(ExtractorStatus.UNRESOLVED,
                reason=(f"$..{leaf} matches {len(named)} nodes and the recorded value sits inside a per-run "
                        "list, so no stable JSONPath selects it — match #1 would grab the wrong element "
                        "under load."),
                suggestion=_json_suggestion(leaf))


def _check_regex(dec: CorrelationDecision, producer: NormalizedRequest) -> ExtractorCheck:
    use_headers = dec.producer_location.startswith(("set-cookie:", "response.header:", "response.location:"))
    text = _headers_text(producer) if use_headers else (producer.response.body.raw or "")
    target = _norm(dec.value)

    def make(status: ExtractorStatus, reason: str = "", suggestion: str = "") -> ExtractorCheck:
        return ExtractorCheck(variable=dec.variable, value=dec.value, producer_index=dec.producer_index,
                              extractor=dec.extractor, status=status, expression=dec.expression,
                              reason=reason, suggestion=suggestion, consumers=list(dec.consumers))

    if not dec.expression:
        return make(ExtractorStatus.UNRESOLVED,
                    reason="no extractor pattern was produced for this value.", suggestion=_regex_suggestion())
    try:
        matches = [m.group(1) for m in _re.finditer(dec.expression, text) if m.groups()]
    except _re.error:
        return make(ExtractorStatus.UNRESOLVED,
                    reason="the produced extractor pattern is not a valid regex.", suggestion=_regex_suggestion())
    if matches and _norm(matches[0]) == target:                # match #1 (what the emitter uses) is correct
        return make(ExtractorStatus.UNIQUE)
    return make(ExtractorStatus.UNRESOLVED,
                reason=("the extractor pattern does not match the recorded value in the producing response "
                        "(match #1 differs) — it would fall back to NOT_FOUND at run time."),
                suggestion=_regex_suggestion())


def verify_extractors(cap: NormalizedCapture,
                      correlations: list[CorrelationDecision]) -> list[ExtractorCheck]:
    """Resolve every non-cookie correlation's extractor against its producing response; classify each
    UNIQUE / AMBIGUOUS_REFINED / UNRESOLVED. Cookie-manager correlations are replayed by JMeter and have
    no explicit extractor to verify, so they are skipped."""
    by_index = {r.context.index: r for r in cap.requests}
    checks: list[ExtractorCheck] = []
    for dec in correlations:
        if dec.extractor == ExtractorType.COOKIE_MANAGER:
            continue
        producer = by_index.get(dec.producer_index)
        if producer is None:
            checks.append(ExtractorCheck(
                variable=dec.variable, value=dec.value, producer_index=dec.producer_index,
                extractor=dec.extractor, status=ExtractorStatus.UNRESOLVED, expression=dec.expression,
                reason="the producing request is not present in the capture.",
                suggestion=_regex_suggestion(), consumers=list(dec.consumers)))
            continue
        if dec.extractor == ExtractorType.JSON:
            checks.append(_check_json(dec, producer))
        else:
            checks.append(_check_regex(dec, producer))
    return checks
