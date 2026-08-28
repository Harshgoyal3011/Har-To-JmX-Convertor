"""Milestone 10 tests — entity-based parameterization + CSV optimizer."""
from __future__ import annotations

from pathlib import Path

from har2jmx.classify import classify_capture
from har2jmx.ir.build import build_capture
from har2jmx.parameterize import build_parameterization

FIX = Path(__file__).parent / "fixtures"


def _plan(name: str):
    cap = build_capture((FIX / name).read_bytes())
    classify_capture(cap)
    return build_parameterization(cap)


def test_existing_entity_becomes_entity_dataset():
    plan = _plan("sample_flow.har")
    ds = {d.name: d for d in plan.datasets}
    assert "Customer" in ds
    cust = ds["Customer"]
    assert cust.source == "entity"
    assert any(c.entity_field == "id" and c.sample == "1001" for c in cust.columns)


def test_runtime_values_never_in_datasets():
    plan = _plan("sample_flow.har")
    all_values = {v for d in plan.datasets for row in d.rows for v in row.values()}
    assert "ORD1" not in all_values          # created object id is a correlation, not test data


def test_unused_master_data_is_skipped_not_a_csv():
    # sample_entities: entities are read but never reused in a request → no datasets, all skipped.
    plan = _plan("sample_entities.har")
    assert plan.datasets == []
    assert any("never used in a request" in reason for _, reason in plan.skipped)


def test_business_inputs_consolidate_into_one_dataset():
    plan = _plan("sample_params.har")
    ds = {d.name: d for d in plan.datasets}
    assert "Inputs" in ds
    cols = {c.name for c in ds["Inputs"].columns}
    assert "email" in cols and "password" in cols
    # consolidated: NOT one CSV per field
    assert len(plan.datasets) == 1


def test_created_id_never_leaks_into_csv_even_with_existing_ids():
    # an entity id column that mixes an existing id (1) and a created runtime id (101) must NOT put
    # the created value into a dataset; the user inputs (title/body) still parameterize.
    plan = _plan("sample_mixed_id.har")
    post = next((d for d in plan.datasets if d.name == "Post"), None)
    assert post is not None
    cols = {c.name for c in post.columns}
    assert "title" in cols and "body" in cols
    assert "id" not in cols
    all_values = {v for d in plan.datasets for row in d.rows for v in row.values()}
    assert "101" not in all_values          # created post id is runtime, never test data


def test_no_csv_per_field_explosion():
    plan = _plan("sample_flow.har")
    # a handful of meaningful datasets, never dozens of fragments
    assert len(plan.datasets) <= 3


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for fn in fns:
        try:
            fn()
        except AssertionError as e:
            print(f"FAIL  {fn.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            print(f"ERROR {fn.__name__}: {type(e).__name__}: {e}")
        else:
            passed += 1
            print(f"ok    {fn.__name__}")
    print(f"\n{passed}/{len(fns)} passed")
    raise SystemExit(0 if passed == len(fns) else 1)
