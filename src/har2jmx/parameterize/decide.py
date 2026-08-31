"""Milestone 10 — entity-based parameterization + CSV optimizer.

Turns BUSINESS_MASTER_DATA verdicts (M8) into a small number of **entity-centric** datasets with
aligned rows (M6), not a CSV per field or per value. Need-gated: a value becomes a parameter only if
it is actually used in a request; runtime values never enter a dataset; datasets with no usable rows
are rejected. Non-entity business inputs (credentials, search terms) consolidate into one `Inputs`
dataset rather than fragmenting.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from har2jmx.classify import ClassificationResult, ValueClass, classify_values
from har2jmx.entities import RelationshipModel, discover_relationships
from har2jmx.ir.normalized import NormalizedCapture
from har2jmx.lineage import LineageGraph, build_lineage
from har2jmx.utils import variable_name


@dataclass
class ParameterColumn:
    name: str
    sample: str = ""
    entity_field: str | None = None


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
class ParameterizationPlan:
    datasets: list[ParameterDataset] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)   # (name, reason)


def _field_from_location(loc: str) -> str:
    tail = loc.split(":", 1)[1] if ":" in loc else loc
    return tail.split(".")[-1] or "value"


def build_parameterization(cap: NormalizedCapture,
                           classification: ClassificationResult | None = None,
                           model: RelationshipModel | None = None,
                           lineage: LineageGraph | None = None) -> ParameterizationPlan:
    lineage = lineage if lineage is not None else build_lineage(cap)
    classification = classification if classification is not None else classify_values(cap, lineage)
    model = model if model is not None else discover_relationships(cap)

    # need-gate: only values that actually appear in a request are usable test data
    request_values = {o.raw.strip() for f in lineage.flows for o in f.occurrences if o.side == "request"}
    request_values |= {f.value for f in lineage.flows if any(o.side == "request" for o in f.occurrences)}

    plan = ParameterizationPlan()
    entity_cols: dict[str, dict[str, str]] = {}   # entity -> {column_name: entity_field}
    inputs: dict[str, str] = {}                    # column_name -> sample value

    for v in classification.parameters():
        if v.value not in request_values:
            plan.skipped.append((v.value, "master data never used in a request"))
            continue
        if v.entity and v.entity_field:
            entity_cols.setdefault(v.entity, {})[variable_name(v.entity_field)] = v.entity_field
        else:
            inputs.setdefault(variable_name(_field_from_location(v.source)), v.value)

    # Values the server generated at runtime — these are correlations and must NEVER sit in a CSV,
    # even when they are an entity's identifier (e.g. a created orderId).
    runtime_values = {v.value for v in classification.verdicts if v.classification == ValueClass.RUNTIME_GENERATED}

    ident = {e.name: e.identifier for e in model.entities}
    for ent, cols in entity_cols.items():
        idf = ident.get(ent)
        if idf:
            cols.setdefault(variable_name(idf), idf)          # keep identity for referential meaning
        rows_src = model.instances.get(ent, [])
        # drop any column that carries a runtime-generated value (a created/server id belongs in
        # correlation, never in a CSV — even if some of the column's other values are existing data)
        dropped = set()
        for col, fld in cols.items():
            vals = [str(r.get(fld)) for r in rows_src if r.get(fld) not in (None, "")]
            if any(v in runtime_values for v in vals):
                dropped.add(col)
        cols = {c: f for c, f in cols.items() if c not in dropped}
        rows = []
        seen_rows: set[tuple] = set()
        for r in rows_src:
            row = {col: ("" if r.get(fld) is None else str(r.get(fld))) for col, fld in cols.items()}
            if not any(val != "" for val in row.values()):
                continue
            key = tuple(row[col] for col in cols)
            if key in seen_rows:                      # distinct rows only — no duplicate test data
                continue
            seen_rows.add(key)
            rows.append(row)
        if not cols or not rows:
            plan.skipped.append((ent, "no usable rows for parameterization"))
            continue
        columns = [
            ParameterColumn(name=col, sample=rows[0].get(col, ""), entity_field=fld)
            for col, fld in cols.items()
        ]
        plan.datasets.append(ParameterDataset(
            name=ent, columns=columns, rows=rows, source="entity",
            reason=f"{len(rows)} distinct {ent} record(s) selected as existing test data",
        ))

    if inputs:
        columns = [ParameterColumn(name=c, sample=s, entity_field=None) for c, s in inputs.items()]
        plan.datasets.append(ParameterDataset(
            name="Inputs", columns=columns, rows=[dict(inputs)], source="inputs",
            reason="client-supplied business inputs (credentials, search terms, form fields)",
        ))

    _consolidate_single_row(plan)
    plan.datasets.sort(key=lambda d: (d.source != "entity", d.name))
    return plan


def _consolidate_single_row(plan: ParameterizationPlan) -> None:
    """Collapse every single-row dataset into one row-per-user ``TestData`` set.

    A CSV earns a separate file only when it has more than one row — that is the only case where
    threads read *different* values. A single-row dataset feeds every virtual user the same value, so
    N of them are N files of noise (a small flow can otherwise emit six one-line CSVs). Merging them
    into one row is lossless — there is no cross-row alignment to preserve — and yields the structure
    a load test actually wants: one row = one virtual user's complete data, extend it with more rows
    to add users. Multi-row datasets stay separate; they carry real per-thread variation.
    """
    single = [d for d in plan.datasets if d.row_count == 1]
    if len(single) < 2:
        return                                    # nothing to gain from merging one (or none)
    multi = [d for d in plan.datasets if d.row_count != 1]

    columns: list[ParameterColumn] = []
    row: dict[str, str] = {}
    for d in single:
        for col in d.columns:
            value = str(d.rows[0].get(col.name, col.sample))
            name = col.name
            if name in row and row[name] != value:          # same column name, different value
                name = variable_name(f"{d.name}_{col.name}")  # qualify to keep both distinct
            if name in row:
                continue
            row[name] = value
            columns.append(ParameterColumn(name=name, sample=value, entity_field=col.entity_field))

    plan.datasets = multi + [ParameterDataset(
        name="TestData", columns=columns, rows=[row], source="inputs",
        reason=("single-value test data merged into one row-per-user dataset — one row is one user's "
                "data; add rows to add users (separate files only where values vary per thread)"),
    )]
