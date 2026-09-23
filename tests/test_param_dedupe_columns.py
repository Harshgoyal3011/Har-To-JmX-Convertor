"""Regression tests: CSV parameter variable names must be unique across datasets.

Two different entities can each expose a field of the same name (a Product ``id`` and an authenticated
user ``id``). Emitting two CSV Data Sets that both declare ``${id}`` is a silent data-mixup in JMeter —
``/products/${id}`` could be fed the user id. The parameterizer must qualify colliding names so each
request reads the value it recorded.
"""
from __future__ import annotations

import re
from pathlib import Path

from har2jmx.emit import build_jmx_xml
from har2jmx.engine import analyze
from har2jmx.parameterize.decide import (
    ParameterColumn,
    ParameterDataset,
    ParameterizationPlan,
    _dedupe_column_names,
)

EXAMPLES = Path(__file__).parent.parent / "examples"


def _csv_cols(xml: str) -> list[str]:
    cols: list[str] = []
    for names in re.findall(r'variableNames">([^<]+)<', xml):
        cols += [c.strip() for c in names.split(",") if c.strip()]
    return cols


def test_dedupe_qualifies_colliding_names_and_keeps_singletons():
    plan = ParameterizationPlan(datasets=[
        ParameterDataset(name="Product", source="entity", rows=[{"id": "144"}],
                         columns=[ParameterColumn(name="id", sample="144")]),
        ParameterDataset(name="Auth", source="entity",
                         rows=[{"id": "1", "username": "bob"}],
                         columns=[ParameterColumn(name="id", sample="1"),
                                  ParameterColumn(name="username", sample="bob")]),
    ])
    _dedupe_column_names(plan)
    names = [c.name for d in plan.datasets for c in d.columns]
    assert len(names) == len(set(names))                      # all unique across datasets
    assert "Product_id" in names and "Auth_id" in names       # colliding 'id' qualified by dataset
    assert "username" in names                                # non-colliding name untouched
    prod = next(d for d in plan.datasets if d.name == "Product")
    assert prod.rows[0].get("Product_id") == "144"            # row keys renamed in lock-step
    assert "id" not in prod.rows[0]


def test_no_dataset_emits_a_duplicate_variable_end_to_end():
    src = EXAMPLES / "dummyjson.har"
    if not src.exists():
        import pytest
        pytest.skip("dummyjson.har example not present")
    res = analyze(src.read_bytes())
    xml = build_jmx_xml(res, {"threads": "5"}).decode()
    cols = _csv_cols(xml)
    assert len(cols) == len(set(cols)), f"duplicate CSV variable name(s): {cols}"
    # the product detail path reads a uniquely-named id variable (fed from the Product dataset)
    m = re.search(r'/products/\$\{(\w+)\}', xml)
    assert m, "product path should substitute a parameter"
    assert cols.count(m.group(1)) == 1                        # that variable comes from exactly one CSV
