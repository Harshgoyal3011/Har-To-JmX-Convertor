"""Entity-based parameterization gated by the parameter-intent engine.

Turns BUSINESS_MASTER_DATA (M8) into entity-centric datasets only when a PE would vary the
value between users/iterations. Intent is decided in ``intent.py`` (lifecycle + slot +
provenance). Correlation, lineage matching, and M8 classification are not modified here.

Need-gated: unused master data never becomes a CSV. Runtime values never enter a dataset.
UNKNOWN intents are REVIEW, not columns. Non-entity user inputs consolidate into ``Inputs``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from har2jmx.classify import ClassificationResult, ValueClass, classify_values
from har2jmx.entities import RelationshipModel, discover_relationships
from har2jmx.ir.normalized import BodyKind, NormalizedCapture
from har2jmx.lineage import LineageGraph, build_lineage
from har2jmx.parameterize.intent import (
    IntentDecision,
    ParameterAction,
    ParameterIntent,
    ParameterSlot,
    decide_intents,
)
from har2jmx.utils import variable_name


@dataclass
class ParameterColumn:
    name: str
    sample: str = ""
    entity_field: str | None = None
    intent: str = ""
    logical_field: str = ""
    producer_index: int | None = None
    producer_location: str = ""
    original: str = ""
    normalized: str = ""
    slots: list[ParameterSlot] = field(default_factory=list)
    controller: str = ""


@dataclass
class ParameterDataset:
    name: str
    columns: list[ParameterColumn]
    rows: list[dict]                 # aligned rows keyed by column name
    source: str                      # "entity" | "inputs"
    reason: str = ""

    @property
    def row_count(self) -> int:
        return len(self.rows)


@dataclass
class ParameterReview:
    value: str
    intent: str
    reason: str
    logical_field: str = ""
    slots: list[str] = field(default_factory=list)


@dataclass
class ParameterizationPlan:
    datasets: list[ParameterDataset] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)   # (name, reason)
    review: list[ParameterReview] = field(default_factory=list)


def _column_from_decision(name: str, d: IntentDecision, sample: str, entity_field: str | None) -> ParameterColumn:
    return ParameterColumn(
        name=name,
        sample=sample,
        entity_field=entity_field,
        intent=d.intent.value,
        logical_field=d.logical_field,
        producer_index=d.producer_index,
        producer_location=d.producer_location,
        original=d.value,
        normalized=d.value,
        slots=list(d.slots),
        controller=d.controller,
    )


def _record_skip(plan: ParameterizationPlan, d: IntentDecision) -> None:
    plan.skipped.append((d.value, d.reason))
    if d.action == ParameterAction.REVIEW:
        plan.review.append(ParameterReview(
            value=d.value,
            intent=d.intent.value,
            reason=d.reason,
            logical_field=d.logical_field,
            slots=[s.location for s in d.slots if s.side == "request"][:8],
        ))


def build_parameterization(cap: NormalizedCapture,
                           classification: ClassificationResult | None = None,
                           model: RelationshipModel | None = None,
                           lineage: LineageGraph | None = None) -> ParameterizationPlan:
    lineage = lineage if lineage is not None else build_lineage(cap)
    classification = classification if classification is not None else classify_values(cap, lineage)
    model = model if model is not None else discover_relationships(cap)

    plan = ParameterizationPlan()
    # Intent over master-data candidates AND unknowns (unknowns → REVIEW, never CSV).
    candidates = [v for v in classification.verdicts
                  if v.classification in {ValueClass.BUSINESS_MASTER_DATA, ValueClass.UNKNOWN, ValueClass.STATIC}]
    decisions = decide_intents(cap, lineage, candidates)
    by_value = {d.value: d for d in decisions}

    runtime_values = {v.value for v in classification.verdicts if v.classification == ValueClass.RUNTIME_GENERATED}

    entity_cols: dict[str, dict[str, str]] = {}   # entity -> {column_name: entity_field}
    entity_decisions: dict[str, dict[str, IntentDecision]] = {}
    inputs: dict[str, IntentDecision] = {}

    for d in decisions:
        if d.value in runtime_values or d.intent == ParameterIntent.SERVER_RUNTIME_STATE:
            plan.skipped.append((d.value, d.reason or "runtime state — not test data"))
            continue
        if d.action != ParameterAction.PARAMETERIZE:
            _record_skip(plan, d)
            continue
        if d.entity and d.entity_field and d.intent != ParameterIntent.USER_INPUT:
            col = variable_name(d.entity_field)
            entity_cols.setdefault(d.entity, {})[col] = d.entity_field
            entity_decisions.setdefault(d.entity, {})[col] = d
        else:
            fields = [
                s.field or d.logical_field or "value"
                for s in d.slots
                if s.side == "request" and not s.excluded
                and s.slot_kind in {"path", "query", "body", "xml", "header"}
            ] or [d.logical_field or "value"]
            seen_f: set[str] = set()
            for fld in fields:
                col = variable_name(fld)
                if col in seen_f:
                    continue
                seen_f.add(col)
                inputs.setdefault(col, d)

    _promote_request_siblings(cap, decisions, inputs)

    ident = {e.name: e.identifier for e in model.entities}
    for ent, cols in entity_cols.items():
        idf = ident.get(ent)
        # Only keep the identity column when that identifier itself survived intent (selected/used).
        if idf and variable_name(idf) not in cols:
            pass
        rows_src = model.instances.get(ent, [])
        dropped = set()
        for col, fld in cols.items():
            vals = [str(r.get(fld)) for r in rows_src if r.get(fld) not in (None, "")]
            if any(v in runtime_values for v in vals):
                dropped.add(col)
        cols = {c: f for c, f in cols.items() if c not in dropped}
        ed = entity_decisions.get(ent, {})
        consumed = {d.value for d in ed.values()} | {
            d.value for d in decisions
            if d.action == ParameterAction.PARAMETERIZE and d.entity == ent
        }
        # List/search may return many records; only rows whose values were actually consumed
        # in a later request belong in the CSV (the selected product, not 99 unused siblings).
        if consumed:
            filtered = [
                r for r in rows_src
                if any(str(r.get(fld, "")) in consumed for fld in cols.values())
            ]
            if filtered:
                rows_src = filtered
        rows = []
        seen_rows: set[tuple] = set()
        for r in rows_src:
            row = {col: ("" if r.get(fld) is None else str(r.get(fld))) for col, fld in cols.items()}
            if not any(val != "" for val in row.values()):
                continue
            key = tuple(row[col] for col in cols)
            if key in seen_rows:
                continue
            seen_rows.add(key)
            rows.append(row)
        if not cols or not rows:
            plan.skipped.append((ent, "no usable rows for parameterization"))
            continue
        columns = []
        for col, fld in cols.items():
            d = ed.get(col) or by_value.get(rows[0].get(col, ""), None)
            sample = rows[0].get(col, "")
            if d is None:
                columns.append(ParameterColumn(name=col, sample=sample, entity_field=fld))
            else:
                columns.append(_column_from_decision(col, d, sample, fld))
        plan.datasets.append(ParameterDataset(
            name=ent, columns=columns, rows=rows, source="entity",
            reason=f"{len(rows)} distinct {ent} record(s) selected as existing test data",
        ))

    if inputs:
        columns = [_column_from_decision(c, d, d.value, None) for c, d in inputs.items()]
        plan.datasets.append(ParameterDataset(
            name="Inputs", columns=columns, rows=[{c: d.value for c, d in inputs.items()}],
            source="inputs",
            reason="client-supplied business inputs (credentials, search terms, form fields)",
        ))

    _consolidate_single_row(plan)
    plan.datasets.sort(key=lambda d: (d.source != "entity", d.name))
    return plan


def _request_input_values(req) -> list[str]:
    vals = [str(v) for _, v in req.request.query]
    vals += [str(v) for _, v in req.request.body.form]
    body = req.request.body.json
    if req.request.body.kind == BodyKind.GRAPHQL and isinstance(body, dict):
        body = body.get("variables") or {}
    if body is not None:
        stack = [body]
        while stack:
            obj = stack.pop()
            if isinstance(obj, dict):
                for v in obj.values():
                    if isinstance(v, (dict, list)):
                        stack.append(v)
                    elif v not in (None, True, False) and not isinstance(v, bool):
                        vals.append(str(v))
            elif isinstance(obj, list):
                stack.extend(obj)
    return vals


def _promote_request_siblings(
    cap: NormalizedCapture,
    decisions: list[IntentDecision],
    inputs: dict[str, IntentDecision],
) -> None:
    """If one input slot on a request is parameterized, keep sibling slots that are also
    PARAMETERIZE on that same request (lat+lon, bbox, amount+currency, origin+destination)."""
    by_value = {d.value: d for d in decisions}
    present = {d.value for d in inputs.values()}
    for req in cap.requests:
        if req.classification.excluded:
            continue
        siblings = [by_value.get(v) for v in _request_input_values(req)]
        siblings = [d for d in siblings if d is not None]
        if not any(d.action == ParameterAction.PARAMETERIZE for d in siblings):
            continue
        for d in siblings:
            if d.value in present:
                continue
            if d.action != ParameterAction.PARAMETERIZE:
                continue
            col = variable_name(d.logical_field or "value")
            if col not in inputs:
                inputs[col] = d
                present.add(d.value)


def _consolidate_single_row(plan: ParameterizationPlan) -> None:
    """Collapse every single-row dataset into one row-per-user ``TestData`` set."""
    single = [d for d in plan.datasets if d.row_count == 1]
    if len(single) < 2:
        return
    multi = [d for d in plan.datasets if d.row_count != 1]

    columns: list[ParameterColumn] = []
    row: dict[str, str] = {}
    for d in single:
        for col in d.columns:
            value = str(d.rows[0].get(col.name, col.sample))
            name = col.name
            if name in row and row[name] != value:
                name = variable_name(f"{d.name}_{col.name}")
            if name in row:
                continue
            row[name] = value
            columns.append(ParameterColumn(
                name=name, sample=value, entity_field=col.entity_field,
                intent=col.intent, logical_field=col.logical_field,
                producer_index=col.producer_index, producer_location=col.producer_location,
                original=col.original or value, normalized=col.normalized or value,
                slots=list(col.slots), controller=col.controller,
            ))

    plan.datasets = multi + [ParameterDataset(
        name="TestData", columns=columns, rows=[row], source="inputs",
        reason=("single-value test data merged into one row-per-user dataset — one row is one user's "
                "data; add rows to add users (separate files only where values vary per thread)"),
    )]
