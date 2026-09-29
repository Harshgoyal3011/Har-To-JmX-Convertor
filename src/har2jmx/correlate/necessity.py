"""Correlation necessity gate.

Discovery stays high-recall. Emission is the minimum set a performance engineer would extract
for a multi-VU script. Provenance and producer-document shape decide this — not field-name lists.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from urllib.parse import parse_qsl, urlparse

from har2jmx.classify import ClassificationResult, Lifecycle, ValueClass
from har2jmx.correlate.decide import CorrelationDecision, ExtractorType
from har2jmx.ir.normalized import NormalizedCapture, NormalizedRequest
from har2jmx.lineage import LineageGraph
from har2jmx.patterns import GUID_RE, PAGINATION_TOKEN_RE

_JWT_RE = re.compile(r"^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$")
_VERSION_SEG = re.compile(r"^v?\d+(?:\.\d+)*$")

# IANA/OAuth vocabulary that appears as JSON *array elements* in discovery documents.
_PROTOCOL_ENUMS = {
    "query", "fragment", "form_post", "none",
    "code", "token", "id_token", "id_token token", "code id_token", "code token",
    "authorization_code", "implicit", "refresh_token", "client_credentials", "password",
    "s256", "plain", "public", "confidential",
}

_CREDENTIAL_HEADERS = {
    "authorization", "proxy-authorization", "x-csrf-token", "x-xsrf-token",
    "x-access-token", "x-auth-token",
}


class RejectionKind(str, Enum):
    CONFIGURATION = "configuration"
    PROTOCOL_METADATA = "protocol_metadata"
    MASTER_DATA = "master_data"
    SUPERSEDED = "superseded"
    NO_CONSUMER = "no_consumer"
    REVIEW = "review"


@dataclass
class RejectedCorrelation:
    decision: CorrelationDecision
    kind: RejectionKind
    reason: str


@dataclass
class CorrelationAudit:
    candidates: list[CorrelationDecision] = field(default_factory=list)
    emitted: list[CorrelationDecision] = field(default_factory=list)
    rejected: list[RejectedCorrelation] = field(default_factory=list)

    def count(self, kind: RejectionKind) -> int:
        return sum(1 for r in self.rejected if r.kind == kind)


def apply_necessity_gate(
    cap: NormalizedCapture,
    lineage: LineageGraph,
    classification: ClassificationResult,
    candidates: list[CorrelationDecision],
) -> CorrelationAudit:
    audit = CorrelationAudit(candidates=list(candidates))
    kept: list[CorrelationDecision] = []
    for d in candidates:
        kind, reason = _classify_necessity(cap, lineage, classification, d)
        if kind is None:
            kept.append(d)
        else:
            audit.rejected.append(RejectedCorrelation(d, kind, reason))

    kept.sort(key=lambda d: (-len(d.value), d.producer_index, d.variable))
    emitted: list[CorrelationDecision] = []
    for d in kept:
        parent = next((p for p in emitted if _covers(p, d)), None)
        if parent is not None:
            audit.rejected.append(RejectedCorrelation(
                d, RejectionKind.SUPERSEDED,
                f"runtime dependency already covered by ${{{parent.variable}}} — no independent extractor",
            ))
            continue
        emitted.append(d)
    emitted.sort(key=lambda d: (d.producer_index, d.variable))
    audit.emitted = emitted
    return audit


def _classify_necessity(
    cap: NormalizedCapture,
    lineage: LineageGraph,
    classification: ClassificationResult,
    d: CorrelationDecision,
) -> tuple[RejectionKind | None, str]:
    if not d.consumers:
        return RejectionKind.NO_CONSUMER, "no downstream consumer — dead extractor"

    flow = lineage.by_value(d.value)
    if flow is None or flow.first_producer is None:
        return RejectionKind.NO_CONSUMER, "no proven producer"

    producer_req = cap.requests[d.producer_index] if 0 <= d.producer_index < len(cap.requests) else None
    verdict = classification.by_value(d.value)
    loc = d.producer_location or ""

    if d.extractor == ExtractorType.COOKIE_MANAGER:
        return None, ""
    if _looks_like_runtime_secret(d.value):
        return None, ""
    if loc.startswith(("set-cookie:", "response.locpath:", "response.location:", "response.regex:")):
        return None, ""
    if loc.startswith(("response.html:", "response.meta:")):
        if GUID_RE.search(str(d.value)) and len(str(d.value)) <= 40:
            return RejectionKind.CONFIGURATION, (
                "hidden-form value is a stable app identifier — the same for every VU"
            )
        if _is_static_route_or_url(d.value):
            return RejectionKind.CONFIGURATION, (
                "hidden-form value is a fixed URL or path — the same for every VU"
            )
        return None, ""
    if _consumed_as_credential(flow):
        return None, ""
    if producer_req is not None and producer_req.method in {"POST", "PUT", "PATCH"}:
        return None, ""
    if flow.first_producer and PAGINATION_TOKEN_RE.search(flow.first_producer.field or ""):
        return None, ""
    if verdict is not None and "pagination" in (verdict.reason or "").lower():
        return None, ""

    if producer_req is not None and _is_protocol_array_member(d.value, producer_req):
        return RejectionKind.PROTOCOL_METADATA, (
            "value is a protocol capability token from a discovery/config array — hardcoded, not per-VU state"
        )

    if _is_static_route_or_url(d.value):
        return RejectionKind.CONFIGURATION, (
            "fixed path or URL with no per-session identity — the same for every VU"
        )

    if producer_req is not None and _is_capability_or_config_document(producer_req) and _is_config_shaped_value(d.value):
        return RejectionKind.CONFIGURATION, (
            "produced by a capability/configuration document and reused as app settings — "
            "the same for every user, not session state"
        )

    if (verdict is not None
            and verdict.classification == ValueClass.BUSINESS_MASTER_DATA
            and verdict.lifecycle == Lifecycle.EXISTING_BEFORE_RUN):
        return RejectionKind.MASTER_DATA, "existing catalog/master identity — parameterize, do not correlate"

    return None, ""


def _consumed_as_credential(flow) -> bool:
    return any(
        (o.location or "").lower().startswith("request.header:")
        and (o.field or "").lower() in _CREDENTIAL_HEADERS
        for o in flow.consumers
    )


def _looks_like_runtime_secret(value: str) -> bool:
    s = str(value).strip()
    if _JWT_RE.match(s):
        return True
    if _url_carries_runtime_query(s):
        return True
    if GUID_RE.search(s) and len(s) <= 40:
        return False
    if s.startswith(("http://", "https://")):
        return False
    if len(s) < 16:
        return False
    letters = sum(c.isalpha() for c in s)
    digits = sum(c.isdigit() for c in s)
    return letters >= 4 and digits >= 2 and len(set(s)) >= 8


def _is_config_shaped_value(value: str) -> bool:
    """Stable identifiers/URLs/paths — not session secrets. No field-name checks."""
    s = str(value).strip()
    if _looks_like_runtime_secret(s):
        return False
    if GUID_RE.search(s) and len(s) <= 40:
        return True
    if _is_static_route_or_url(s):
        return True
    if len(s) <= 64 and s.replace("_", "").replace("-", "").isalnum() and not _looks_like_runtime_secret(s):
        return True
    return False


def _is_protocol_array_member(value: str, producer: NormalizedRequest) -> bool:
    j = producer.response.body.json
    if not isinstance(j, dict):
        return False
    val = str(value)
    for v in j.values():
        if not isinstance(v, list):
            continue
        as_str = [str(x) for x in v]
        if val not in as_str:
            continue
        if val.lower() in _PROTOCOL_ENUMS:
            return True
        if len(val) <= 24 and val.replace("_", "").replace("-", "").isalpha():
            return True
    return False


def _is_capability_or_config_document(req: NormalizedRequest) -> bool:
    if req.method not in {"GET", "HEAD"}:
        return False
    path = (req.request.path or "").lower()
    if "well-known" in path or "openid-configuration" in path:
        return True
    j = req.response.body.json
    if not isinstance(j, dict) or len(j) < 3:
        return False
    proto_lists = 0
    urls = 0
    guids = 0
    lists = 0
    for v in j.values():
        if isinstance(v, str) and v.startswith(("http://", "https://")):
            urls += 1
        if isinstance(v, str) and GUID_RE.search(v) and len(v) <= 40:
            guids += 1
        if isinstance(v, list) and v:
            lists += 1
            if any(str(x).lower() in _PROTOCOL_ENUMS for x in v[:16]):
                proto_lists += 1
    return proto_lists >= 1 or urls >= 2 or (urls >= 1 and guids >= 1) or (guids >= 2 and len(j) >= 4)


def _is_static_route_or_url(value: str) -> bool:
    s = str(value).strip()
    if _url_carries_runtime_query(s):
        return False
    if s.startswith("/") and "://" not in s:
        return _path_has_no_runtime_identity(s)
    if s.startswith(("http://", "https://")):
        try:
            p = urlparse(s)
        except Exception:  # noqa: BLE001
            return False
        return _path_has_no_runtime_identity(p.path or "/")
    return False


def _path_has_no_runtime_identity(path: str) -> bool:
    if GUID_RE.search(path or ""):
        return False
    segs = [p for p in (path or "").split("/") if p]
    if not segs:
        return False
    for seg in segs:
        if _VERSION_SEG.match(seg):
            continue
        if len(seg) >= 12 and any(c.isdigit() for c in seg) and any(c.isalpha() for c in seg):
            return False
    return True


def _url_carries_runtime_query(value: str) -> bool:
    if "://" not in str(value) or "?" not in str(value):
        return False
    try:
        q = parse_qsl(urlparse(str(value)).query, keep_blank_values=True)
    except Exception:  # noqa: BLE001
        return False
    for _, v in q:
        if GUID_RE.search(v) or _JWT_RE.match(v) or _looks_like_runtime_secret(v):
            return True
        if len(v) >= 12 and any(c.isdigit() for c in v) and any(c.isalpha() for c in v):
            return True
    return False


def _covers(parent: CorrelationDecision, child: CorrelationDecision) -> bool:
    """Same payload already carries this value as part of a longer extracted URL/blob."""
    if parent is child or parent.value == child.value:
        return False
    if child.value not in parent.value:
        return False
    if len(parent.value) < len(child.value) + 2:
        return False
    if parent.producer_index != child.producer_index:
        return False
    return set(child.consumers) <= set(parent.consumers)
