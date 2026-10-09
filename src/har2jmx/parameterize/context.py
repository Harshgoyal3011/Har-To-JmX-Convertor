"""Read-only slot context for test-data necessity, independent of correlation rules.

Role vocabularies describe transport, observation and control structures. They are
not application catalogs or lists of individual browser timing field names.
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import unquote

from har2jmx.ir.normalized import BodyKind, NormalizedRequest
from har2jmx.lineage import Occurrence


def words(name: str) -> set[str]:
    split = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", name or "")
    return set(re.findall(r"[a-z]+", split.lower()))


def field_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


_IDENTITY = {"username", "signinname", "loginname", "loginhint", "email", "user", "login"}
_SECRET_INPUT = {"password", "passwd", "pwd", "pass", "otp", "pin", "passcode", "onetimecode"}
_SEARCH = {"q", "query", "search", "searchterm", "keyword", "keywords", "term", "cat", "category", "tag"}
_OBSERVATION = {"telemetry", "metrics", "diagnostics", "instrumentation", "performance", "timing", "rum"}
_CONTROL = {"page", "pagination", "sort", "sorting", "ordering", "cache", "version", "capability"}
_USER_SEMANTICS = {
    "name", "email", "phone", "mobile", "address", "city", "country", "postal", "zip", "date",
    "dob", "quantity", "qty", "amount", "price", "lat", "latitude", "lon", "longitude", "bbox",
    "origin", "destination", "location", "prompt", "message", "content", "comment", "description",
    "note", "question", "feedback", "subject", "title", "body", "reference", "criteria", "count",
    "year", "currency", "code",
}


def credential_kind(field: str) -> str:
    # Qualified form/structured names retain the credential meaning of their
    # explicit leaf (e.g. pf.username). Do not infer from arbitrary prefixes.
    key = field_key((field or "").rsplit(".", 1)[-1])
    if key in _IDENTITY:
        return "identity"
    if key in _SECRET_INPUT:
        return "secret"
    return ""


def _objects_at(body: Any, location: str) -> list[dict]:
    """Ancestors of a structured slot; lineage paths omit list indices."""
    if not location.startswith("request.body:"):
        return []
    parts = location.split(":", 1)[1].split(".")
    nodes = [body]
    ancestors = []
    for part in parts:
        expanded = []
        for node in nodes:
            expanded.extend(node if isinstance(node, list) else [node])
        nodes = []
        for node in expanded:
            if isinstance(node, dict):
                ancestors.append(node)
                if part in node:
                    nodes.append(node[part])
    return ancestors


def _observation_shape(obj: dict) -> bool:
    keys = set().union(*(words(str(k)) for k in obj)) if obj else set()
    # PerformanceEntry is a record describing a browser event/resource, together
    # with measurements. Unknown fields within that record inherit its role.
    if {"entry", "type", "duration"} <= keys and keys & {"start", "initiator", "navigation"}:
        return True
    numeric = [k for k, v in obj.items() if isinstance(v, (int, float)) and not isinstance(v, bool)]
    clock_fields = [k for k in numeric if words(str(k)) & {"start", "end"}]
    if len(clock_fields) >= 4 and keys & {"navigation", "dom", "connection", "lookup", "fetch"}:
        return True
    if {"navigation", "timing", "entries"} <= keys:
        return True
    if _environment_event(obj):
        return True
    # Instrumentation batches describe event records plus producer metadata.
    # A mixed business payload is not an envelope: classify only its event
    # descendants, so ordinary business fields remain eligible as inputs.
    event_keys = {
        k for k, v in obj.items()
        if isinstance(v, list) and v and all(isinstance(e, dict) and _environment_event(e) for e in v)
    }
    envelope_keys = {"application", "appversion", "version", "schema", "source", "service",
                     "environment", "metadata", "context"}
    if event_keys and all(k in event_keys or field_key(str(k)) in envelope_keys for k in obj):
        return True
    # Custom metric records need measurement structure AND diagnostic context.
    return bool(keys & _OBSERVATION and keys & {"samples", "measurements", "histogram", "unit", "timestamp"})


def _environment_event(obj: dict) -> bool:
    """Multiple environment namespaces distinguish observation from business events."""
    if not any(words(str(k)) & {"timestamp", "time"} for k in obj):
        return False
    attributes = obj.get("attributes")
    if not isinstance(attributes, dict):
        return False
    namespaces = {str(k).split(".", 1)[0].lower() for k in attributes if "." in str(k)}
    environment = {"browser", "window", "document", "navigator", "screen", "cpu", "device", "os", "uname", "engine"}
    return len(namespaces & environment) >= 3


def slot_role(req: NormalizedRequest, o: Occurrence) -> tuple[str, str]:
    """Classify the role of a request occurrence, never its dynamic appearance."""
    loc = o.location.lower()
    field = field_key(o.field)
    path_words = words(req.path)
    slot_words = words(o.location.split(":", 1)[-1])
    ancestors = _objects_at(req.request.body.json, o.location)
    if (loc.startswith("request.body:") and slot_words & _OBSERVATION) or any(
        _observation_shape(a) for a in ancestors
    ):
        return "telemetry", "measurement/diagnostic record or observation subtree, not tester-controlled data"
    if loc.startswith("request.body:") and slot_words & {"config", "configuration", "settings", "capabilities"}:
        return "configuration", "configuration/capability subtree, without user-input evidence"
    # Endpoint evidence is useful for opaque telemetry schemas, but is not a
    # request exclusion: the original noise classification remains untouched.
    if path_words & {"telemetry", "perftrace", "beacon", "analytics", "diagnostics"}:
        return "telemetry", "observation endpoint; client instrumentation is not test data"
    if loc.startswith("request.header:"):
        return "technical", "request header without evidence of user selection"
    if loc.startswith("request.cookie:"):
        return "runtime", "cookie state belongs to Cookie Manager/correlation"
    if slot_words & _CONTROL or field in {"pageno", "pagenumber", "pagesize", "limit", "offset", "timezone"}:
        return "configuration", "pagination/order/cache/environment control, not a business scenario input"
    if "orderdimensions" in loc or "pagedimensions" in loc:
        return "configuration", "query execution controls (sort/page), not user-entered business filters"
    if credential_kind(o.field) and loc.startswith(("request.body:", "request.query:", "request.xml:")):
        return "input", "explicit credential/challenge answer slot submitted by the client"
    # OAuth/OIDC requests separate credential entry from protocol negotiation.
    auth_protocol = bool(path_words & {"oauth", "oauth2", "openid", "authorize", "token"})
    if auth_protocol or ".well-known" in req.path:
        return "configuration", "authentication negotiation/discovery slot, not a login input"
    if field in {"requesttype", "appid", "applicationid", "clientinfo", "codechallengemethod", "responsemode"}:
        return "configuration", "technical request/application/protocol control"
    if loc.startswith("request.path"):
        return "route", "route literal requires explicit input or selected-record evidence"
    if loc.startswith(("request.body:", "request.query:", "request.xml:")):
        if field in _SEARCH or words(o.field) & _USER_SEMANTICS or field.endswith(
            ("name", "date", "address", "number", "code", "checkin", "checkout")
        ):
            return "input", "input semantics in a request payload/query, with client provenance"
        if field.endswith(("id", "number")) and loc.startswith(("request.body:", "request.query:", "request.xml:")):
            return "input", "record/reference supplied in an action payload; provenance must establish selection/input"
        if req.request.body.kind == BodyKind.GRAPHQL and loc.startswith("request.body:variables."):
            return "input", "GraphQL operation argument, distinct from the protocol envelope"
        # An unfamiliar field is supported by an explicit action payload rather
        # than a domain-specific dictionary. Opaque RPC blobs remain reviewable.
        action = path_words & {"create", "submit", "save", "update", "register", "checkout", "search", "book"}
        if action and loc.startswith(("request.body:", "request.xml:")):
            return "input", "client argument in an explicit business action payload"
        if req.request.body.kind in {BodyKind.FORM, BodyKind.MULTIPART} and loc.startswith("request.body:"):
            return "input", "submitted form field with client provenance, outside protocol/observation controls"
    return "unknown", "request presence alone does not prove tester control or test-data necessity"


def first_request_value(flow) -> bool:
    requests = [o.request_index for o in flow.occurrences if o.side == "request"]
    responses = [o.request_index for o in flow.occurrences if o.side == "response"]
    return bool(requests) and (not responses or min(requests) <= min(responses))


def selected_record(req: NormalizedRequest, o: Occurrence, v, producer) -> bool:
    """Require record identity/context, not merely equality with a read response."""
    if producer is not None and words(producer.location) & {
        "config", "configuration", "settings", "capabilities", "telemetry", "metrics", "diagnostics",
    }:
        return False
    if v.is_identifier and v.entity and producer is not None:
        return True
    key = field_key(o.field)
    if key.endswith(("id", "number", "code", "ref", "reference")) and o.location.startswith(
        ("request.body:", "request.query:", "request.xml:")
    ):
        return True
    if o.location.startswith("request.path") and producer is not None:
        pkey = field_key(producer.field)
        if pkey in {"id", "key", "code", "ref", "identifier"} or pkey.endswith(("id", "number", "ref")):
            return True
        # A response-returned compound catalog identity used verbatim in a path.
        return "/" in unquote(o.raw).strip("/")
    return False
