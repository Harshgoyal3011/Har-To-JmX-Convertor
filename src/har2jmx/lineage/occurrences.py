"""Inspection-only occurrence substrate; equality buckets are evidence, not owners.

No lifecycle, dependency, entity or parameterization decisions are made here.
The index is built explicitly so existing conversion paths remain unchanged.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import unquote, unquote_plus, urlsplit

from har2jmx.ir.normalized import NormalizedCapture
from har2jmx.lineage.graph import _AUTH_HEADERS, _SCHEME_RE, LineageGraph, _norm, build_lineage


def _digest(parts: Any) -> str:
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


@dataclass(frozen=True)
class ValueOccurrence:
    """One scalar observation/representation, never a logical runtime owner.

    Paths use typed components, avoiding dotted-key and array-index ambiguity.
    A representation parent records an explicit local transformation only; it
    does not prove a relationship to another request or response.
    """

    identity: str
    capture_identity: str
    event_identity: str
    request_index: int
    side: str
    origin: str
    host: str
    source_request_identity: str
    source_response_identity: str | None
    location: str
    structured_path: tuple[str | int, ...]
    array_indices: tuple[int, ...]
    pair_index: int | None
    original_type: str
    original_spelling: str
    spelling_source: str
    normalized_representation: str
    representation_kind: str
    transforms: tuple[str, ...]
    representation_parent: str | None = None
    literal_compatibility_bucket: str | None = None


class OccurrenceIndex:
    """Exact-ID lookup and explicitly non-authoritative literal evidence lookup."""

    def __init__(self, occurrences: list[ValueOccurrence], capture_identity: str):
        self.capture_identity = capture_identity
        self.occurrences = tuple(occurrences)
        self._by_identity = {o.identity: o for o in occurrences}
        if len(self._by_identity) != len(occurrences):
            raise ValueError("duplicate occurrence coordinates")
        buckets: dict[str, list[ValueOccurrence]] = defaultdict(list)
        for occurrence in occurrences:
            if occurrence.literal_compatibility_bucket is not None:
                buckets[occurrence.literal_compatibility_bucket].append(occurrence)
        self._literal_buckets = {key: tuple(value) for key, value in buckets.items()}

    def by_identity(self, identity: str) -> ValueOccurrence | None:
        return self._by_identity.get(identity)

    def literal_evidence(self, value: Any) -> tuple[ValueOccurrence, ...]:
        """Return observations in a legacy bucket; never select a producer."""
        # _norm is not idempotent for nested percent encodings. An exact
        # compatibility key must not be decoded a second time during lookup.
        return self._literal_buckets.get(str(value), self._literal_buckets.get(_norm(value), ()))

    def inspect(self) -> dict[str, Any]:
        """HAR/IR spelling -> exact identity -> compatibility bucket debug view."""
        return {
            "capture_identity": self.capture_identity,
            "identity_is_literal": False,
            "occurrences": [asdict(o) for o in self.occurrences],
        }


def _scalars(obj: Any):
    # Independent inspection inventory: no policy traversal limits and no
    # scalar-array exclusion. This does not add correlation candidates.
    pending = [((), obj)]
    while pending:
        path, value = pending.pop()
        if isinstance(value, dict):
            pending.extend((path + (str(k),), v) for k, v in reversed(list(value.items())))
        elif isinstance(value, list):
            pending.extend((path + (i,), v) for i, v in reversed(list(enumerate(value))))
        else:
            yield path, value


def _type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    return "string"


def _capture_identity(cap: NormalizedCapture) -> str:
    digest = hashlib.sha256()
    for req in cap.requests:
        # Length-prefixed serialization keeps repeated events and captures
        # separate. Caller may supply a persistent capture identity instead.
        part = json.dumps(
            [
                req.index,
                req.context.started,
                req.request.url,
                req.method,
                req.request.headers,
                req.request.cookies,
                req.request.body.raw,
                req.request.body.form,
                req.request.body.json,
                req.response.status,
                req.response.headers,
                req.response.set_cookies,
                req.response.body.raw,
                req.response.body.json,
            ],
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode()
        digest.update(str(len(part)).encode() + b":" + part)
    return digest.hexdigest()


def build_occurrence_index(
    cap: NormalizedCapture, lineage: LineageGraph | None = None, *, capture_identity: str | None = None
) -> OccurrenceIndex:
    """Build alongside a legacy lineage inventory without modifying it or the IR.

    Original JSON lexemes (quotes/escapes/numeric exponent spelling) have already
    been decoded by the reader; spelling_source states that limitation. Raw URL
    query/path spellings are available and retained. No transformation is
    inferred between unrelated occurrences merely because their values match.
    """
    lineage = lineage if lineage is not None else build_lineage(cap)
    scope = capture_identity if capture_identity is not None else _capture_identity(cap)
    evidence_values = {f.value for f in lineage.flows}
    out: list[ValueOccurrence] = []
    for req in cap.requests:
        request_id = _digest([scope, req.index, "request"])
        response_id = _digest([scope, req.index, "response"])
        event_id = _digest([scope, req.index, "event"])
        scheme = req.request.scheme.lower()
        host = req.request.host.lower()
        port = req.request.port or ("443" if scheme == "https" else "80")
        origin = f"{scheme}://{host}:{port}"

        def add(
            side,
            location,
            path,
            value,
            kind,
            pair_index=None,
            spelling_source="normalized_ir",
            transforms=(),
            parent=None,
            normalization_value=None,
            req=req,
            event_id=event_id,
            origin=origin,
            host=host,
            request_id=request_id,
            response_id=response_id,
        ):
            spelling = str(value) if not isinstance(value, (bool, type(None))) else json.dumps(value)
            normalized = _norm(value if normalization_value is None else normalization_value)
            changes = list(transforms)
            if spelling.strip() != spelling:
                changes.append("compatibility_whitespace_trim")
            if "%" in str(value if normalization_value is None else normalization_value):
                changes.append("compatibility_percent_decode")
            identity = _digest([scope, req.index, side, location, path, pair_index, _type(value), kind])
            occurrence = ValueOccurrence(
                identity,
                scope,
                event_id,
                req.index,
                side,
                origin,
                host,
                request_id,
                response_id if side == "response" else None,
                location,
                tuple(path),
                tuple(p for p in path if isinstance(p, int)) if kind == "json_scalar" else (),
                pair_index,
                _type(value),
                spelling,
                spelling_source,
                normalized,
                kind,
                tuple(changes),
                parent,
                normalized if normalized in evidence_values else None,
            )
            out.append(occurrence)
            return identity

        segments = [s for s in req.request.path.split("/") if s]
        for i, raw in enumerate(segments):
            add(
                "request",
                "request.path",
                (i,),
                raw,
                "url_path_segment",
                i,
                "request_url",
                ("url_percent_decode",) if unquote(raw) != raw else (),
                normalization_value=unquote(raw),
            )
        query = urlsplit(req.request.url).query
        if query:
            for i, pair in enumerate(query.split("&")):
                key, _, raw = pair.partition("=")
                add(
                    "request",
                    "request.query:" + unquote_plus(key),
                    (unquote_plus(key),),
                    raw,
                    "url_query_value",
                    i,
                    "request_url",
                    ("url_form_decode",) if unquote_plus(raw) != raw else (),
                    normalization_value=unquote_plus(raw),
                )
        for side, pairs, prefix, kind in [
            ("request", req.request.headers, "request.header:", "header_value"),
            ("request", req.request.cookies, "request.cookie:", "cookie_value"),
            ("request", req.request.body.form, "request.body:", "form_value"),
            ("response", req.response.headers, "response.header:", "header_value"),
            ("response", req.response.set_cookies, "set-cookie:", "cookie_value"),
        ]:
            for i, (name, value) in enumerate(pairs):
                parent = add(side, prefix + name, (name,), value, kind, i)
                if side == "request" and prefix == "request.header:" and name.lower() in _AUTH_HEADERS:
                    match = _SCHEME_RE.match(value)
                    if match:
                        add(
                            side,
                            prefix + name,
                            (name,),
                            match.group(2),
                            "credential_payload",
                            i,
                            transforms=("credential_scheme_removed",),
                            parent=parent,
                        )
        for side, body in [("request", req.request.body), ("response", req.response.body)]:
            if body.json is not None:
                for path, value in _scalars(body.json):
                    add(
                        side,
                        side + ".body",
                        path,
                        value,
                        "json_scalar",
                        spelling_source="decoded_json_scalar",
                    )
    # Preserve candidate evidence for embedded HTML/XML/regex and synthetic
    # catalog-key observations lacking a direct IR scalar location. Their
    # legacy coordinate is explicit, with a stable ordinal, not guessed indices.
    represented = set()
    for occurrence in out:
        location = occurrence.location
        if occurrence.representation_kind == "json_scalar":
            path = occurrence.structured_path
            body = (
                cap.requests[occurrence.request_index].request.body
                if occurrence.side == "request"
                else cap.requests[occurrence.request_index].response.body
            )
            if occurrence.side == "request" and body.kind.value == "graphql" and path[:1] == ("variables",):
                path = path[1:]
            location += ":" + ".".join(p for p in path if isinstance(p, str))
        represented.add(
            (occurrence.request_index, occurrence.side, location, occurrence.normalized_representation)
        )
    legacy_ordinals: dict[tuple, int] = defaultdict(int)
    for flow in lineage.flows:
        for old in dict.fromkeys(flow.occurrences + flow.producers):
            if (old.request_index, old.side, old.location, flow.value) in represented:
                continue
            req = cap.requests[old.request_index]
            coordinate = (old.request_index, old.side, old.location)
            i = legacy_ordinals[coordinate]
            legacy_ordinals[coordinate] += 1
            origin = f"{req.request.scheme}://{req.host}:{req.request.port or ('443' if req.request.scheme == 'https' else '80')}"
            identity = _digest([scope, old.request_index, old.side, old.location, i, "legacy_observation"])
            out.append(
                ValueOccurrence(
                    identity,
                    scope,
                    _digest([scope, old.request_index, "event"]),
                    old.request_index,
                    old.side,
                    origin,
                    req.host,
                    _digest([scope, old.request_index, "request"]),
                    _digest([scope, old.request_index, "response"]) if old.side == "response" else None,
                    old.location,
                    (),
                    (),
                    i,
                    "unknown",
                    old.raw,
                    "legacy_lineage_observation",
                    flow.value,
                    "legacy_observation",
                    (),
                    None,
                    flow.value,
                )
            )
    return OccurrenceIndex(out, scope)
