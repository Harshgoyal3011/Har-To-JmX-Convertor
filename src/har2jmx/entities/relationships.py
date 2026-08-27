"""Milestone 6 — entity relationships & aligned instance rows.

Links the entities found in M5 (Ward→Patient, Customer→Order, Patient→Visit) using structural
evidence — foreign-key attributes, URL path nesting, JSON nesting, and same-response co-occurrence —
and preserves each entity's observed rows *aligned* (patientId 1 stays paired with its own name and
wardId), so downstream test-data generation never scrambles related values.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from har2jmx.entities.discovery import (
    BusinessEntity,
    _ID_SUFFIX_RE,
    _is_id_field,
    _singularize,
    _titleize,
    discover_entities,
    extract_entity_records,
)
from har2jmx.ir.normalized import NormalizedCapture

_ID_SEG_RE = re.compile(r"^(?:\d+|[0-9a-fA-F]{8,}|[0-9a-fA-F-]{16,})$")
_VERSION_RE = re.compile(r"^v\d+$", re.IGNORECASE)
_API_WORDS = {"api", "rest", "service", "services", "ws", "rpc", "gql", "graphql", "odata", "web", "app"}

_KIND_CONF = {"foreign_key": "High", "path": "High", "nested": "Medium", "co_response": "Medium"}
_KIND_RANK = {"foreign_key": 0, "path": 1, "nested": 2, "co_response": 3}


@dataclass
class Relationship:
    parent: str
    child: str
    kind: str                 # foreign_key | path | nested | co_response
    via: str = ""
    confidence: str = "Medium"
    evidence: list[str] = field(default_factory=list)


@dataclass
class RelationshipModel:
    entities: list[BusinessEntity]
    relationships: list[Relationship]
    instances: dict[str, list[dict]]     # aligned rows per entity
    ordered_entities: list[str]          # topological: parents before children

    def children_of(self, name: str) -> list[str]:
        return [r.child for r in self.relationships if r.parent == name]

    def parents_of(self, name: str) -> list[str]:
        return [r.parent for r in self.relationships if r.child == name]


def _entity_from_token(token: str, names: set[str]) -> str | None:
    cand = _titleize(_singularize(token.lower()))
    return cand if cand in names else None


def _path_nouns(path_segments: list[str]) -> list[str]:
    out = []
    for seg in path_segments:
        low = seg.lower()
        if not low or _ID_SEG_RE.match(low) or _VERSION_RE.match(low) or any(c.isdigit() for c in low):
            continue
        if low in _API_WORDS:
            continue
        out.append(low)
    return out


def _build_instances(records, entities: list[BusinessEntity]) -> dict[str, list[dict]]:
    """Group records into aligned rows per entity, merging rows that share an identifier value."""
    ident = {e.name: e.identifier for e in entities}
    rows: dict[str, list[dict]] = {}
    keyed: dict[str, dict[str, dict]] = {}   # entity -> id value -> merged row
    for rec in records:
        if rec.entity not in ident:
            continue
        idf = ident[rec.entity]
        if idf and idf in rec.scalars:
            k = str(rec.scalars[idf])
            bucket = keyed.setdefault(rec.entity, {})
            merged = bucket.setdefault(k, {})
            for a, v in rec.scalars.items():
                merged.setdefault(a, v)      # keep first-seen; rows stay internally aligned
        else:
            rows.setdefault(rec.entity, []).append(dict(rec.scalars))
    for ent, bucket in keyed.items():
        rows.setdefault(ent, [])
        rows[ent] = list(bucket.values()) + rows[ent]
    return rows


def _topo_order(names: list[str], rels: list[Relationship]) -> list[str]:
    children: dict[str, set[str]] = {n: set() for n in names}
    indeg: dict[str, int] = {n: 0 for n in names}
    for r in rels:
        if r.parent in children and r.child in indeg and r.child not in children[r.parent]:
            children[r.parent].add(r.child)
            indeg[r.child] += 1
    queue = sorted([n for n in names if indeg[n] == 0])
    order: list[str] = []
    while queue:
        n = queue.pop(0)
        order.append(n)
        for c in sorted(children[n]):
            indeg[c] -= 1
            if indeg[c] == 0:
                queue.append(c)
    for n in names:                          # append any left over (cycles)
        if n not in order:
            order.append(n)
    return order


def discover_relationships(cap: NormalizedCapture, entities: list[BusinessEntity] | None = None) -> RelationshipModel:
    entities = entities if entities is not None else discover_entities(cap)
    names = {e.name for e in entities}
    records = extract_entity_records(cap)

    raw: dict[tuple[str, str], Relationship] = {}

    def link(parent: str, child: str, kind: str, via: str, evidence: str) -> None:
        if parent == child or parent not in names or child not in names:
            return
        key = (parent, child)
        existing = raw.get(key)
        if existing is None or _KIND_RANK[kind] < _KIND_RANK[existing.kind]:
            raw[key] = Relationship(parent, child, kind, via, _KIND_CONF[kind], [evidence])
        elif evidence not in existing.evidence:
            existing.evidence.append(evidence)

    # 1) foreign keys — an attribute <other>Id that names another entity
    for e in entities:
        for attr in (a.name for a in e.attributes):
            if not _is_id_field(attr) or attr == e.identifier:
                continue
            prefix = _ID_SUFFIX_RE.sub("", attr)
            parent = _entity_from_token(prefix, names)
            if parent:
                link(parent, e.name, "foreign_key", attr, f"{e.name}.{attr} references {parent}")

    # 2) URL path nesting — /parent/{id}/child
    for req in cap.requests:
        if req.classification.excluded:
            continue
        nouns = [_entity_from_token(n, names) for n in _path_nouns(req.request.path_segments)]
        nouns = [n for n in nouns if n]
        for parent, child in zip(nouns, nouns[1:]):
            link(parent, child, "path", req.request.path, f"path {req.request.path}")

    # 3) JSON nesting — child object emitted inside a parent entity's subtree
    for rec in records:
        if rec.parent_entity and rec.parent_entity in names:
            link(rec.parent_entity, rec.entity, "nested", "json nesting", f"{rec.entity} nested in {rec.parent_entity}")

    # 4) same-response co-occurrence — the path-primary entity parents the others
    by_source: dict[int, set[str]] = {}
    for rec in records:
        if rec.source_kind == "response":
            by_source.setdefault(rec.source_index, set()).add(rec.entity)
    idx_to_req = {r.index: r for r in cap.requests}
    for idx, ents in by_source.items():
        if len(ents) < 2:
            continue
        req = idx_to_req.get(idx)
        primary = None
        if req:
            for n in reversed(_path_nouns(req.request.path_segments)):
                cand = _entity_from_token(n, names)
                if cand in ents:
                    primary = cand
                    break
        if primary:
            for other in ents:
                link(primary, other, "co_response", req.request.path if req else "", "same response payload")

    relationships = sorted(raw.values(), key=lambda r: (_KIND_RANK[r.kind], r.parent, r.child))
    instances = _build_instances(records, entities)
    ordered = _topo_order([e.name for e in entities], relationships)
    return RelationshipModel(entities=entities, relationships=relationships, instances=instances, ordered_entities=ordered)
