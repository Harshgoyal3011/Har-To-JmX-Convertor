"""Final variable ownership, independent of discovery and lifecycle decisions."""

from __future__ import annotations

import hashlib
import json
from collections import Counter

from har2jmx.correlate import ExtractorType
from har2jmx.emit.redirects import location_variable
from har2jmx.utils import variable_name

_PLAN_VARIABLES = {"BASE_URL", "PROTOCOL", "THREADS", "LOOPS", "RAMP", "HOLD", "THINKTIME", "TIMEOUT"}


def parameter_identity(dataset, column) -> str:
    """Identity uses provenance, never the captured value or allocation order."""
    slots = sorted({(s.request_index, s.location, s.field, s.side) for s in column.slots})
    return json.dumps(
        [dataset.name, dataset.source, column.logical_field, column.entity_field, column.name, slots],
        ensure_ascii=False, separators=(",", ":"),
    )


class VariableBindings:
    """Keep existing names unless a test input conflicts with another owner.

    Runtime names remain unchanged, preserving auth/redirect references. Owned
    CSV names are derived from logical provenance and applied at every emission
    site, without mutating the parameterization or correlation decision objects.
    """

    def __init__(self, result):
        runtime = {c.variable for c in result.correlations if c.extractor != ExtractorType.COOKIE_MANAGER}
        generated = {location_variable(r.index) for r in result.capture.requests}
        reserved = runtime | generated | _PLAN_VARIABLES
        identities = {
            parameter_identity(dataset, column): column.name
            for dataset in result.parameterization.datasets for column in dataset.columns
        }
        counts = Counter(identities.values())
        occupied = reserved | set(identities.values())
        self.names: dict[str, str] = {}
        for identity, original in sorted(identities.items()):
            name = original
            if original in reserved or counts[original] > 1:
                digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
                stem = "input_" + variable_name(original)
                # A pre-existing user/runtime name may itself look like one of
                # our names. Extend the stable digest instead of using order.
                width = 12
                name = f"{stem}_{digest[:width]}"
                while name in occupied:
                    width += 1
                    if width > len(digest):
                        stem += "_input"
                        width = 12
                    name = f"{stem}_{digest[:width]}"
            occupied.add(name)
            self.names[identity] = name

    def parameter_name(self, dataset, column) -> str:
        return self.names[parameter_identity(dataset, column)]

    def parameter_rows(self, dataset) -> list[dict]:
        """Bind a conflicting identity's captured row to its own source input.

        Independent entity datasets can share a name while their first rows
        contain a different sample than the source slot assigned to a column.
        Separating those names alone still supplies the wrong semantic value.
        For a renamed owner with one unambiguous captured input, use that input
        in its initial row. Later observed rows and discovery decisions remain
        intact; no values are generated and no decision object is mutated.
        """
        rows = [dict(row) for row in dataset.rows]
        if not rows:
            return rows
        for column in dataset.columns:
            if self.parameter_name(dataset, column) == column.name:
                continue
            values = {s.normalized for s in column.slots
                      if s.side == "request" and not s.excluded and s.normalized != ""}
            if len(values) == 1:
                rows[0][column.name] = next(iter(values))
        return rows
