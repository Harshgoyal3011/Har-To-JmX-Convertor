"""Milestone 7 — value lineage / dependency graph.

Traces every significant value: producer(s) → value → consumer(s), across path, query, headers,
cookies, JSON/form/GraphQL bodies, response headers, and Set-Cookie.

Two properties fix the old engine's biggest defect (loose substring matching that produced hundreds
of bogus consumers):

* **Position-aware, whole-slot matching.** Values are compared as complete structured slots
  (a query value, a body-field value, a path segment, a header/cookie value) — never as substrings
  of a blob — so `SID-abc123` is not "consumed" by a request that merely contains the text `SID`.
* **Transform-aware equality.** Values are normalized (trimmed, str()-ed, URL-unquoted) so a JSON
  integer `12345`, the string `"12345"`, and the path segment `/x/12345` are recognized as one value.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterator
from urllib.parse import unquote

from har2jmx.ir.normalized import BodyKind, NormalizedCapture, NormalizedRequest
from har2jmx.patterns import GUID_RE

# Headers whose value carries a credential after a scheme word (Bearer <token>, Token <t>, …).
_AUTH_HEADERS = {"authorization", "proxy-authorization", "x-auth-token", "x-access-token",
                 "x-api-key", "x-csrf-token", "x-xsrf-token"}
_SCHEME_RE = re.compile(r"^\s*(\S+)\s+(\S.*)$")

_TRIVIAL = {"", "true", "false", "null", "none", "undefined", "0", "1", "-1"}
_MAX_LIST = 25
_MAX_DEPTH = 6

# Header names that never carry correlated state — skip to avoid noise.
_NOISE_HEADERS = {
    "accept", "accept-encoding", "accept-language", "accept-charset", "user-agent", "referer",
    "origin", "host", "content-type", "content-length", "connection", "cache-control", "pragma",
    "upgrade-insecure-requests", "dnt", "te", "date", "expires", "last-modified", "vary",
    "content-encoding", "transfer-encoding", "keep-alive", "server", "x-powered-by",
    "x-aspnet-version", "cookie", "set-cookie", "content-disposition", "etag_",
}


@dataclass(frozen=True)
class Occurrence:
    request_index: int
    side: str          # "request" | "response"
    location: str      # e.g. "request.query:id", "response.body:user.id", "request.path", "set-cookie:SID"
    field: str         # param / key / header / cookie name (or "path")
    raw: str           # value as originally seen


@dataclass
class ValueFlow:
    value: str                                   # normalized canonical value
    occurrences: list[Occurrence] = field(default_factory=list)
    producers: list[Occurrence] = field(default_factory=list)   # response-side occurrences
    consumers: list[Occurrence] = field(default_factory=list)   # request occurrences after first producer
    first_producer: Occurrence | None = None
    significant: bool = False

    @property
    def is_produced_then_consumed(self) -> bool:
        return self.first_producer is not None and bool(self.consumers)

    @property
    def consumer_indices(self) -> list[int]:
        return sorted({o.request_index for o in self.consumers})


@dataclass
class LineageGraph:
    flows: list[ValueFlow]

    def by_value(self, value: str) -> ValueFlow | None:
        v = _norm(value)
        return next((f for f in self.flows if f.value == v), None)

    def produced_then_consumed(self) -> list[ValueFlow]:
        return [f for f in self.flows if f.is_produced_then_consumed]

    def request_only(self) -> list[ValueFlow]:
        return [f for f in self.flows if not f.producers and f.occurrences]


# ---------------------------------------------------------------- normalization / significance

def _norm(v: Any) -> str:
    s = str(v).strip()
    if "%" in s:
        try:
            s = unquote(s)
        except Exception:  # noqa: BLE001
            pass
    return s


def _is_significant(v: str) -> bool:
    if GUID_RE.search(v):
        return True
    if len(v) >= 8:
        return True
    if len(v) >= 4:
        return True          # short but non-trivial (OX-9, 1001)
    return False


# ---------------------------------------------------------------- slot extraction

def _scalar(v: Any) -> bool:
    return isinstance(v, (str, int, float)) and not isinstance(v, bool)


def _walk_json(obj: Any, prefix: str, out: list[tuple[str, Any]], depth: int = 0) -> None:
    if depth > _MAX_DEPTH:
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            kp = f"{prefix}.{k}" if prefix else str(k)
            if _scalar(v):
                out.append((kp, v))
            elif isinstance(v, (dict, list)):
                _walk_json(v, kp, out, depth + 1)
    elif isinstance(obj, list):
        for item in obj[:_MAX_LIST]:
            _walk_json(item, prefix, out, depth + 1)


def _emit(value: Any, side: str, location: str, field_name: str, idx: int) -> Occurrence | None:
    norm = _norm(value)
    if norm.lower() in _TRIVIAL or len(norm) < 2:
        return None
    return Occurrence(request_index=idx, side=side, location=location, field=field_name, raw=str(value))


def _request_slots(req: NormalizedRequest) -> Iterator[Occurrence]:
    idx = req.index
    for i, seg in enumerate(req.request.path_segments):
        o = _emit(unquote(seg), "request", "request.path", "path", idx)
        if o:
            yield o
    for k, v in req.request.query:
        o = _emit(v, "request", f"request.query:{k}", k, idx)
        if o:
            yield o
    for name, value in req.request.headers:
        nl = name.lower()
        if nl in _NOISE_HEADERS or nl.startswith(("sec-", "x-forwarded")):
            continue
        o = _emit(value, "request", f"request.header:{name}", name, idx)
        if o:
            yield o
        # Also expose the credential portion of auth headers (e.g. "Bearer <token>"), so a token
        # issued in a response body is recognized as consumed here despite the scheme prefix.
        if nl in _AUTH_HEADERS and value:
            m = _SCHEME_RE.match(value)
            if m and m.group(2).strip() != value.strip():
                oc = _emit(m.group(2).strip(), "request", f"request.header:{name}", name, idx)
                if oc:
                    yield oc
    for name, value in req.request.cookies:
        o = _emit(value, "request", f"request.cookie:{name}", name, idx)
        if o:
            yield o
    if req.request.body.kind in {BodyKind.FORM, BodyKind.MULTIPART}:
        for k, v in req.request.body.form:
            o = _emit(v, "request", f"request.body:{k}", k, idx)
            if o:
                yield o
    if req.request.body.json is not None:
        body_json = req.request.body.json
        # For GraphQL, the business inputs are the operation variables; operationName/query are
        # protocol envelope, not test data.
        if req.request.body.kind == BodyKind.GRAPHQL and isinstance(body_json, dict):
            body_json = body_json.get("variables") or {}
        pairs: list[tuple[str, Any]] = []
        _walk_json(body_json, "", pairs)
        for kp, v in pairs:
            o = _emit(v, "request", f"request.body:{kp}", kp.split(".")[-1], idx)
            if o:
                yield o


def _response_slots(req: NormalizedRequest) -> Iterator[Occurrence]:
    idx = req.index
    for name, value in req.response.set_cookies:
        o = _emit(value, "response", f"set-cookie:{name}", name, idx)
        if o:
            yield o
    for name, value in req.response.headers:
        if name.lower() in _NOISE_HEADERS or name.lower() == "set-cookie":
            continue
        o = _emit(value, "response", f"response.header:{name}", name, idx)
        if o:
            yield o
    if req.response.body.json is not None:
        pairs: list[tuple[str, Any]] = []
        _walk_json(req.response.body.json, "", pairs)
        for kp, v in pairs:
            o = _emit(v, "response", f"response.body:{kp}", kp.split(".")[-1], idx)
            if o:
                yield o


# ---------------------------------------------------------------- graph construction

def build_lineage(cap: NormalizedCapture) -> LineageGraph:
    index: dict[str, list[Occurrence]] = {}

    def add(o: Occurrence) -> None:
        index.setdefault(_norm(o.raw), []).append(o)

    for req in cap.requests:
        if req.classification.excluded:
            continue
        for o in _request_slots(req):
            add(o)
        for o in _response_slots(req):
            add(o)

    flows: list[ValueFlow] = []
    for value, occ in index.items():
        producers = [o for o in occ if o.side == "response"]
        first_producer = min(producers, key=lambda o: o.request_index) if producers else None
        consumers: list[Occurrence] = []
        if first_producer is not None:
            consumers = [
                o for o in occ
                if o.side == "request" and o.request_index > first_producer.request_index
            ]
        flows.append(ValueFlow(
            value=value,
            occurrences=occ,
            producers=producers,
            consumers=consumers,
            first_producer=first_producer,
            significant=_is_significant(value),
        ))

    flows.sort(key=lambda f: (not f.is_produced_then_consumed, -len(f.consumers), f.value))
    return LineageGraph(flows=flows)
