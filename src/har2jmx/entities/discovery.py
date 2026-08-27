"""Milestone 5 — business entity discovery.

Identifies business entities (Customer, Order, Patient, Ward, …) and groups their attributes from
**payload structure** — not names alone. An entity is a recurring object shape that carries an
identity. Naming is generic (the key an object is nested under, else the URL path noun, else an
`<x>Id` prefix); wrapper/envelope objects (data/result/meta/…) are skipped. No CSVs here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from har2jmx.ir.normalized import NormalizedCapture, NormalizedRequest
from har2jmx.patterns import ID_FIELD_RE

_WRAPPER_NAMES = {
    "data", "result", "results", "items", "item", "list", "records", "record", "rows", "row",
    "content", "payload", "response", "body", "error", "errors", "meta", "metadata", "pagination",
    "page", "pages", "links", "_links", "_embedded", "status", "success", "message", "messages",
    "total", "count", "facets", "aggregations", "value", "values", "attributes", "properties",
}
_API_WORDS = {"api", "rest", "service", "services", "ws", "rpc", "gql", "graphql", "odata", "web", "app", "v"}
_VERB_WORDS = {
    "search", "find", "lookup", "query", "list", "browse", "create", "new", "add", "save",
    "update", "edit", "delete", "remove", "submit", "open", "view", "get", "authenticate",
    "login", "logout", "upload", "export", "download", "connect", "authorize", "token",
}
_ID_SEG_RE = re.compile(r"^(?:\d+|[0-9a-fA-F]{8,}|[0-9a-fA-F-]{16,})$")
_VERSION_RE = re.compile(r"^v\d+$", re.IGNORECASE)
_CAMEL_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_ID_SUFFIX_RE = re.compile(r"(?:_id|Id|ID)$")

_MAX_LIST_ITEMS = 25
_MAX_DEPTH = 6


@dataclass
class EntityAttribute:
    name: str
    is_identifier: bool = False
    sample_value: str = ""
    occurrences: int = 0


@dataclass
class BusinessEntity:
    name: str
    identifier: str | None = None
    attributes: list[EntityAttribute] = field(default_factory=list)
    instance_count: int = 0
    confidence: str = "Medium"
    evidence: list[str] = field(default_factory=list)


# ---------------------------------------------------------------- helpers

def _singularize(word: str) -> str:
    w = word
    if len(w) > 3 and w.endswith("ies"):
        return w[:-3] + "y"
    if len(w) > 3 and w.endswith(("ses", "xes", "zes", "ches", "shes")):
        return w[:-2]
    if len(w) > 2 and w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w


def _titleize(token: str) -> str:
    parts = _CAMEL_RE.sub(" ", token).replace("-", " ").replace("_", " ").split()
    return " ".join(p[:1].upper() + p[1:] for p in parts if p)


def _scalar(v: Any) -> bool:
    return isinstance(v, (str, int, float)) and not isinstance(v, bool)


def _is_id_field(name: str) -> bool:
    return bool(ID_FIELD_RE.search(name)) or name.lower() in {"uuid", "guid"}


def _good_name(name: str | None) -> bool:
    return bool(name) and name.lower() not in _WRAPPER_NAMES and len(name) > 1 and bool(re.search(r"[A-Za-z]", name))


def _path_noun(req: NormalizedRequest) -> str:
    for seg in reversed(req.request.path_segments):
        low = seg.lower()
        if not low or _ID_SEG_RE.match(low) or _VERSION_RE.match(low):
            continue
        # any segment carrying a digit (ORD1, 1001, file2) is an identifier/instance, not a noun
        if any(ch.isdigit() for ch in low):
            continue
        if low in _API_WORDS or low in _VERB_WORDS:
            continue
        return low
    return ""


def _entity_name(scalars: dict[str, Any], key_context: str | None, path_noun: str) -> str | None:
    candidates: list[str] = []
    if key_context:
        candidates.append(key_context)
    if path_noun:
        candidates.append(path_noun)
    for k in scalars:
        if _is_id_field(k):
            prefix = _ID_SUFFIX_RE.sub("", k)
            if prefix and prefix.lower() != k.lower():
                candidates.append(prefix)
    for c in candidates:
        if _good_name(c):
            return _titleize(_singularize(c.lower()))
    return None


# ---------------------------------------------------------------- extraction

@dataclass
class _Record:
    entity: str
    scalars: dict[str, Any]
    identifier_field: str | None
    source_index: int
    source_kind: str            # "request" | "response"
    parent_entity: str | None = None   # nearest enclosing emitted entity (nesting evidence)


def _extract_records(obj: Any, key_context: str | None, path_noun: str,
                     source_index: int, source_kind: str, out: list[_Record], depth: int = 0,
                     ancestor: str | None = None) -> None:
    if depth > _MAX_DEPTH:
        return
    if isinstance(obj, dict):
        scalars = {k: v for k, v in obj.items() if _scalar(v) and str(v).strip() != ""}
        id_fields = [k for k in scalars if _is_id_field(k)]
        emitted = ancestor
        if scalars and (id_fields or len(scalars) >= 2):
            name = _entity_name(scalars, key_context, path_noun)
            if name:
                out.append(_Record(
                    entity=name,
                    scalars=scalars,
                    identifier_field=_pick_identifier(name, list(scalars)),
                    source_index=source_index,
                    source_kind=source_kind,
                    parent_entity=ancestor,
                ))
                emitted = name
        for k, v in obj.items():
            if isinstance(v, (dict, list)):
                _extract_records(v, k, path_noun, source_index, source_kind, out, depth + 1, emitted)
    elif isinstance(obj, list):
        for item in obj[:_MAX_LIST_ITEMS]:
            _extract_records(item, key_context, path_noun, source_index, source_kind, out, depth + 1, ancestor)


def extract_entity_records(cap: NormalizedCapture) -> list[_Record]:
    """Extract raw entity records (aligned scalar rows) from all non-excluded payloads."""
    records: list[_Record] = []
    for req in cap.requests:
        if req.classification.excluded:
            continue
        noun = _path_noun(req)
        if req.request.body.json is not None:
            _extract_records(req.request.body.json, None, noun, req.index, "request", records)
        if req.response.body.json is not None:
            _extract_records(req.response.body.json, None, noun, req.index, "response", records)
    return records


def _pick_identifier(entity_name: str, fields: list[str]) -> str | None:
    entity_key = re.sub(r"[^a-z0-9]", "", entity_name.lower())
    # 1) <entity>id / <entity>_id
    for f in fields:
        fl = re.sub(r"[^a-z0-9]", "", f.lower())
        if fl == entity_key + "id":
            return f
    # 2) plain id
    for f in fields:
        if f.lower() == "id":
            return f
    # 3) any id-like field
    for f in fields:
        if _is_id_field(f):
            return f
    return None


# ---------------------------------------------------------------- aggregation

class _Agg:
    def __init__(self, name: str) -> None:
        self.name = name
        self.attr_occ: dict[str, int] = {}
        self.attr_sample: dict[str, str] = {}
        self.id_values: dict[str, set[str]] = {}   # distinct values per id-like field
        self.sources: set[tuple[int, str]] = set()

    def add(self, rec: _Record) -> None:
        for k, v in rec.scalars.items():
            self.attr_occ[k] = self.attr_occ.get(k, 0) + 1
            self.attr_sample.setdefault(k, str(v))
            if _is_id_field(k):
                self.id_values.setdefault(k, set()).add(str(v))
        self.sources.add((rec.source_index, rec.source_kind))

    def build(self) -> BusinessEntity:
        # choose the identifier deterministically by entity-match precedence, not per-record votes
        identifier = _pick_identifier(self.name, list(self.attr_occ))
        attrs = [
            EntityAttribute(
                name=name,
                is_identifier=(name == identifier) or _is_id_field(name),
                sample_value=self.attr_sample.get(name, ""),
                occurrences=occ,
            )
            for name, occ in sorted(self.attr_occ.items(), key=lambda kv: (-kv[1], kv[0]))
        ]
        instance_count = len(self.id_values.get(identifier, set())) if identifier else len(self.sources)
        if identifier and (len(attrs) >= 3 or instance_count >= 2):
            confidence = "High"
        elif identifier or len(attrs) >= 2:
            confidence = "Medium"
        else:
            confidence = "Low"
        evidence = [
            f"observed in {len(self.sources)} request(s)",
            f"{instance_count} distinct instance(s)" if identifier else f"{len(attrs)} attribute(s)",
        ]
        if identifier:
            evidence.insert(0, f"identity field '{identifier}'")
        return BusinessEntity(
            name=self.name,
            identifier=identifier,
            attributes=attrs,
            instance_count=instance_count,
            confidence=confidence,
            evidence=evidence,
        )


def discover_entities(cap: NormalizedCapture) -> list[BusinessEntity]:
    """Discover business entities and their attributes from request/response payloads."""
    records = extract_entity_records(cap)

    aggs: dict[str, _Agg] = {}
    for rec in records:
        aggs.setdefault(rec.entity, _Agg(rec.entity)).add(rec)

    entities = [agg.build() for agg in aggs.values()]
    # keep only real entities (identifier or ≥2 attributes) and sort by strength
    entities = [e for e in entities if e.identifier or len(e.attributes) >= 2]
    order = {"High": 0, "Medium": 1, "Low": 2}
    entities.sort(key=lambda e: (order.get(e.confidence, 3), -e.instance_count, e.name))
    return entities
