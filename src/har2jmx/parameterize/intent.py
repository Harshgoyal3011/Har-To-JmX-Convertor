"""Parameter intent — would a PE vary this value as test data?

Consumes M8 verdicts and M7 lineage as **evidence**. Does not change correlation, lineage
matching, or value classification. Domain-agnostic: lifecycle + slot shape + who controls the
value, never application/field-name tables.

Intents and actions:

    USER_INPUT                → PARAMETERIZE
    SELECTED_EXISTING_DATA    → PARAMETERIZE
    SERVER_RUNTIME_STATE      → leave to correlation (no CSV)
    STATIC_CONFIGURATION      → HARDCODE (no CSV)
    MASTER_CATALOG_DATA       → HARDCODE unless it is the selected identity slot
    TELEMETRY                 → no CSV
    UNKNOWN                   → REVIEW (no CSV)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from har2jmx.classify import ValueClass
from har2jmx.classify.value_engine import Lifecycle, ValueVerdict
from har2jmx.ir.normalized import NormalizedCapture
from har2jmx.lineage import LineageGraph, Occurrence

# Transport/protocol request headers — IANA/HTTP, not business domains.
_INFRA_HEADERS = {
    "accept", "accept-encoding", "accept-language", "accept-charset", "user-agent", "referer",
    "origin", "host", "content-type", "content-length", "connection", "cache-control", "pragma",
    "cookie", "authorization", "proxy-authorization", "if-none-match", "if-modified-since",
    "if-match", "if-unmodified-since", "range", "te", "expect", "dnt", "upgrade-insecure-requests",
    "content-encoding", "transfer-encoding", "keep-alive", "upgrade", "via", "forwarded",
    "x-forwarded-for", "x-forwarded-host", "x-forwarded-proto", "x-requested-with",
}


class ParameterIntent(str, Enum):
    USER_INPUT = "USER_INPUT"
    SELECTED_EXISTING_DATA = "SELECTED_EXISTING_DATA"
    SERVER_RUNTIME_STATE = "SERVER_RUNTIME_STATE"
    STATIC_CONFIGURATION = "STATIC_CONFIGURATION"
    MASTER_CATALOG_DATA = "MASTER_CATALOG_DATA"
    TELEMETRY = "TELEMETRY"
    UNKNOWN = "UNKNOWN"


class ParameterAction(str, Enum):
    PARAMETERIZE = "PARAMETERIZE"
    HARDCODE = "HARDCODE"
    REVIEW = "REVIEW"
    CORRELATE = "CORRELATE"   # not our job — no CSV


@dataclass
class ParameterSlot:
    """One concrete request (or producing response) location for a value."""
    request_index: int
    location: str
    slot_kind: str
    field: str
    original: str
    normalized: str
    method: str = ""
    excluded: bool = False
    side: str = "request"


@dataclass
class IntentDecision:
    value: str
    intent: ParameterIntent
    action: ParameterAction
    reason: str
    logical_field: str
    producer_index: int | None = None
    producer_location: str = ""
    slots: list[ParameterSlot] = field(default_factory=list)
    entity: str | None = None
    entity_field: str | None = None
    lifecycle: str = ""
    controller: str = ""   # user | selection | server | system | unknown


def _slot_kind(location: str) -> str:
    loc = location.lower()
    if loc.startswith("request.path"):
        return "path"
    if loc.startswith("request.query:"):
        return "query"
    if loc.startswith("request.header:"):
        return "header"
    if loc.startswith("request.cookie:"):
        return "cookie"
    if loc.startswith("request.xml:"):
        return "xml"
    if loc.startswith("request.body:"):
        return "body"
    if loc.startswith("set-cookie:"):
        return "set-cookie"
    if loc.startswith("response."):
        return "response"
    return "other"


def _occurrence_to_slot(cap: NormalizedCapture, o: Occurrence, normalized: str) -> ParameterSlot:
    req = cap.requests[o.request_index] if 0 <= o.request_index < len(cap.requests) else None
    excluded = bool(req and req.classification.excluded)
    method = req.method if req else ""
    return ParameterSlot(
        request_index=o.request_index,
        location=o.location,
        slot_kind=_slot_kind(o.location),
        field=o.field,
        original=o.raw,
        normalized=normalized,
        method=method,
        excluded=excluded,
        side=o.side,
    )


def _path_join_request(cap: NormalizedCapture, value: str) -> int | None:
    """Index of a request whose consecutive path segments join to ``value`` (owner/repo)."""
    if "/" not in str(value):
        return None
    target = str(value).strip("/")
    for req in cap.requests:
        segs = [s for s in req.request.path_segments if s]
        for i in range(len(segs) - 1):
            if "/".join(segs[i:i + 2]) == target:
                return req.index
            if "/".join(segs[i:]) == target:
                return req.index
    return None


def _is_infra_header(o: Occurrence) -> bool:
    if not o.location.lower().startswith("request.header:"):
        return False
    return o.field.lower() in _INFRA_HEADERS


def _is_business_slot(o: Occurrence) -> bool:
    """Slots a PE would consider for test data — not cookies, not protocol headers."""
    kind = _slot_kind(o.location)
    if kind in {"cookie", "set-cookie"}:
        return False
    if kind == "header" and _is_infra_header(o):
        return False
    if o.side != "request":
        return False
    return kind in {"path", "query", "body", "xml", "header", "other"}


def _controller(v: ValueVerdict, live: list[Occurrence]) -> str:
    if v.classification == ValueClass.RUNTIME_GENERATED:
        return "server"
    if v.lifecycle == Lifecycle.USER_INPUT:
        return "user"
    if v.lifecycle == Lifecycle.EXISTING_BEFORE_RUN:
        return "selection"
    if all(_is_infra_header(o) or _slot_kind(o.location) == "cookie" for o in live):
        return "system"
    return "unknown"


def classify_intent(cap: NormalizedCapture, lineage: LineageGraph, v: ValueVerdict) -> IntentDecision:
    """Map one M8 verdict + its lineage flow onto a PE parameterization intent."""
    flow = lineage.by_value(v.value)
    occs = list(flow.occurrences) if flow else []
    req_occs = [o for o in occs if o.side == "request"]
    live = [o for o in req_occs if 0 <= o.request_index < len(cap.requests)
            and not cap.requests[o.request_index].classification.excluded]
    slots = [_occurrence_to_slot(cap, o, str(v.value)) for o in req_occs]
    producer = flow.first_producer if flow else None
    logical = v.entity_field or (producer.field if producer else "") or (
        min(live, key=lambda o: o.request_index).field if live else ""
    ) or (v.source.split(":")[-1] if v.source else "value")
    base = dict(
        value=str(v.value),
        logical_field=logical,
        producer_index=producer.request_index if producer else None,
        producer_location=producer.location if producer else (v.source or ""),
        slots=slots,
        entity=v.entity,
        entity_field=v.entity_field,
        lifecycle=v.lifecycle.value if hasattr(v.lifecycle, "value") else str(v.lifecycle),
        controller=_controller(v, live),
    )

    if v.classification == ValueClass.RUNTIME_GENERATED:
        return IntentDecision(
            intent=ParameterIntent.SERVER_RUNTIME_STATE, action=ParameterAction.CORRELATE,
            reason="server runtime state — correlation owns this value, never a CSV",
            **base,
        )

    if req_occs and not live:
        return IntentDecision(
            intent=ParameterIntent.TELEMETRY, action=ParameterAction.HARDCODE,
            reason="value only sent on excluded (telemetry/static) requests — not test data",
            **base,
        )

    join_req = _path_join_request(cap, str(v.value))
    if not req_occs and join_req is None:
        return IntentDecision(
            intent=ParameterIntent.MASTER_CATALOG_DATA, action=ParameterAction.HARDCODE,
            reason="master data never used in a request",
            **base,
        )
    if not req_occs and join_req is not None:
        join_slot = ParameterSlot(
            request_index=join_req, location="request.path", slot_kind="path",
            field="path", original=str(v.value), normalized=str(v.value),
            method=cap.requests[join_req].method if 0 <= join_req < len(cap.requests) else "",
            excluded=False, side="request",
        )
        base = dict(base)
        base["slots"] = [join_slot]
        return IntentDecision(
            intent=ParameterIntent.SELECTED_EXISTING_DATA, action=ParameterAction.PARAMETERIZE,
            reason="existing record consumed as consecutive path segments",
            **base,
        )

    if not live:
        return IntentDecision(
            intent=ParameterIntent.UNKNOWN, action=ParameterAction.REVIEW,
            reason="no request slot on a business request — nothing to vary at load",
            **base,
        )

    business = [o for o in live if _is_business_slot(o)]
    if not business:
        if all(_slot_kind(o.location) == "cookie" for o in live):
            return IntentDecision(
                intent=ParameterIntent.SERVER_RUNTIME_STATE, action=ParameterAction.CORRELATE,
                reason="only used as a request cookie — Cookie Manager / correlation, not CSV",
                **base,
            )
        return IntentDecision(
            intent=ParameterIntent.STATIC_CONFIGURATION, action=ParameterAction.HARDCODE,
            reason="only used in protocol headers — hardcoded, not test data",
            **base,
        )

    if v.classification == ValueClass.STATIC:
        return IntentDecision(
            intent=ParameterIntent.STATIC_CONFIGURATION, action=ParameterAction.HARDCODE,
            reason="classified static/config — same for every user, leave literal",
            **base,
        )

    if v.classification == ValueClass.UNKNOWN:
        return IntentDecision(
            intent=ParameterIntent.UNKNOWN, action=ParameterAction.REVIEW,
            reason=v.reason or "insufficient evidence to vary as test data",
            **base,
        )

    # BUSINESS_MASTER_DATA (and any other non-runtime, non-static, non-unknown)
    if v.lifecycle == Lifecycle.USER_INPUT:
        return IntentDecision(
            intent=ParameterIntent.USER_INPUT, action=ParameterAction.PARAMETERIZE,
            reason="client-originated input in a business slot — vary per user/iteration",
            **base,
        )

    if v.lifecycle == Lifecycle.EXISTING_BEFORE_RUN:
        # Listed then sent back in path/query/body = the user selected an existing record.
        # Extra catalog attributes that never leave the list response never reach here (no request slot).
        kinds = {_slot_kind(o.location) for o in business}
        if kinds & {"path", "query", "body", "xml"}:
            return IntentDecision(
                intent=ParameterIntent.SELECTED_EXISTING_DATA, action=ParameterAction.PARAMETERIZE,
                reason="existing record returned by a read, then used in a later request slot — CSV identity",
                **base,
            )
        return IntentDecision(
            intent=ParameterIntent.MASTER_CATALOG_DATA, action=ParameterAction.HARDCODE,
            reason="catalog/master value not used in a selectable business slot — do not vary",
            **base,
        )

    return IntentDecision(
        intent=ParameterIntent.UNKNOWN, action=ParameterAction.REVIEW,
        reason="lifecycle unclear — flag for review, do not silently CSV",
        **base,
    )


def decide_intents(cap: NormalizedCapture, lineage: LineageGraph,
                   verdicts: list[ValueVerdict]) -> list[IntentDecision]:
    return [classify_intent(cap, lineage, v) for v in verdicts]
