"""Correlation necessity gate.

Discovery stays high-recall. Emission is the minimum set a performance engineer would extract
for a multi-VU script. Provenance and producer-document shape decide this — not field-name lists.
"""

from __future__ import annotations

import json
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


def _is_jwt(value: str) -> bool:
    s = str(value).strip()
    if not _JWT_RE.match(s):
        return False
    # hostnames like tenant.onmicrosoft.com also have two dots; JWT parts are longer
    return all(len(p) >= 8 for p in s.split("."))
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
    NOT_REQUIRED = "not_required"


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
        kind, reason = _classify_necessity(cap, lineage, classification, d, candidates)
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
    candidates: list[CorrelationDecision],
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
    if _is_jwt(str(d.value).strip()):
        return None, ""
    if loc.startswith(("set-cookie:", "response.locpath:", "response.location:")):
        return None, ""
    if loc.startswith("response.regex:"):
        if producer_req is not None and _is_protocol_array_member(d.value, producer_req):
            return RejectionKind.PROTOCOL_METADATA, (
                "value is a protocol capability token from a discovery/config array — hardcoded, not per-VU state"
            )
        if producer_req is not None and _is_capability_or_config_document(producer_req) and _is_config_shaped_value(d.value):
            return RejectionKind.CONFIGURATION, (
                "embedded in a capability/configuration document — the same for every user, not session state"
            )
        if _is_url_or_path_template(d.value) and not _url_carries_uncorrelated_runtime_query(d.value, candidates):
            return RejectionKind.CONFIGURATION, (
                "fixed path or URL with no independent per-session identity — the same for every VU"
            )
        return None, ""
    if loc.startswith(("response.html:", "response.meta:")):
        if GUID_RE.search(str(d.value)) and len(str(d.value)) <= 40:
            return RejectionKind.CONFIGURATION, (
                "hidden-form value is a stable app identifier — the same for every VU"
            )
        if _is_url_or_path_template(d.value):
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

    if _is_url_or_path_template(d.value):
        if _runtime_query_tokens_covered_by_siblings(d, candidates):
            return RejectionKind.CONFIGURATION, (
                "URL/path is a static template; runtime query tokens are correlated separately"
            )
        if not _url_carries_uncorrelated_runtime_query(d.value, candidates):
            return RejectionKind.CONFIGURATION, (
                "fixed path or URL with no independent per-session identity — the same for every VU"
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
    if s.startswith(("/", "http://", "https://")):
        return False
    if _is_jwt(s):
        return True
    if "." in s or s.count("_") >= 1:
        return False
    if GUID_RE.search(s) and len(s) <= 40:
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
    if _is_url_or_path_template(s):
        return True
    if len(s) <= 64 and s.replace("_", "").replace("-", "").isalnum():
        return True
    return False


def _json_docs(req: NormalizedRequest) -> list:
    docs: list = []
    j = req.response.body.json
    if isinstance(j, (dict, list)):
        docs.append(j)
    elif (req.response.body.raw or "").strip():
        docs.extend(_json_objects_in_text(req.response.body.raw))
    return docs


def _json_objects_in_text(text: str) -> list:
    out: list = []
    n = len(text)
    i = 0
    while i < n and len(out) < 8:
        if text[i] != "{":
            i += 1
            continue
        depth = 0
        for j in range(i, min(i + 250_000, n)):
            ch = text[j]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        obj = json.loads(text[i:j + 1])
                    except (ValueError, TypeError):
                        break
                    if isinstance(obj, dict) and len(obj) >= 2:
                        out.append(obj)
                    break
        i += 1
    return out


def _walk_json(obj):
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _walk_json(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk_json(v)


def _is_protocol_array_member(value: str, producer: NormalizedRequest) -> bool:
    val = str(value)
    for doc in _json_docs(producer):
        for node in _walk_json(doc):
            if not isinstance(node, dict):
                continue
            for v in node.values():
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
    for doc in _json_docs(req):
        if _document_looks_like_config(doc):
            return True
    return False


def _document_looks_like_config(doc) -> bool:
    proto_lists = 0
    urls = 0
    guids = 0
    nodes = 0
    for node in _walk_json(doc):
        if not isinstance(node, dict):
            continue
        nodes += 1
        for v in node.values():
            if isinstance(v, str) and v.startswith(("http://", "https://")):
                urls += 1
            if isinstance(v, str) and GUID_RE.search(v) and len(v) <= 40:
                guids += 1
            if isinstance(v, list) and v and any(str(x).lower() in _PROTOCOL_ENUMS for x in v[:16]):
                proto_lists += 1
    return proto_lists >= 1 or urls >= 2 or (urls >= 1 and guids >= 1) or (guids >= 2 and nodes >= 1)


def _is_url_or_path_template(value: str) -> bool:
    """Host+path is environment routing, even if a query string carries a separate runtime token."""
    s = str(value).strip()
    if s.startswith("/") and "://" not in s:
        return _path_has_no_runtime_identity(s.split("?", 1)[0])
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
        if GUID_RE.search(seg):
            return False
        if _is_jwt(seg) or _looks_like_runtime_secret(seg):
            return False
        if seg.isdigit() and len(seg) >= 4:
            return False
    return True


def _query_runtime_tokens(value: str) -> list[str]:
    if "://" not in str(value) or "?" not in str(value):
        return []
    try:
        q = parse_qsl(urlparse(str(value)).query, keep_blank_values=True)
    except Exception:  # noqa: BLE001
        return []
    tokens: list[str] = []
    for _, v in q:
        if not v:
            continue
        if GUID_RE.search(v) and len(v) <= 40:
            continue
        if _is_jwt(v) or _looks_like_runtime_secret(v):
            tokens.append(v)
        elif len(v) >= 12 and any(c.isdigit() for c in v) and any(c.isalpha() for c in v):
            tokens.append(v)
    return tokens


def _runtime_query_tokens_covered_by_siblings(
    d: CorrelationDecision, candidates: list[CorrelationDecision],
) -> bool:
    tokens = _query_runtime_tokens(d.value)
    if not tokens:
        return False
    others = {c.value for c in candidates if c is not d and c.consumers}
    return all(t in others for t in tokens)


def _url_carries_uncorrelated_runtime_query(
    value: str, candidates: list[CorrelationDecision],
) -> bool:
    tokens = _query_runtime_tokens(value)
    if not tokens:
        return False
    others = {c.value for c in candidates if c.value != value and c.consumers}
    return any(t not in others for t in tokens)


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
