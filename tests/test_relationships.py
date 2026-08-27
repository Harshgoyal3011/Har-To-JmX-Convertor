"""Milestone 6 tests — entity relationships & aligned instance rows.

Runs under pytest, and also directly:  PYTHONPATH=src python tests/test_relationships.py
"""
from __future__ import annotations

from pathlib import Path

from har2jmx.classify import classify_capture
from har2jmx.entities import discover_relationships
from har2jmx.ir.build import build_capture

FIX = Path(__file__).parent / "fixtures"


def _model(name: str):
    cap = build_capture((FIX / name).read_bytes())
    classify_capture(cap)
    return discover_relationships(cap)


def _rel(model, parent, child):
    return next((r for r in model.relationships if r.parent == parent and r.child == child), None)


def test_foreign_key_relationship():
    m = _model("sample_entities.har")
    r = _rel(m, "Ward", "Patient")           # Patient.wardId -> Ward
    assert r is not None
    assert r.kind == "foreign_key" and r.confidence == "High"


def test_nested_or_coresponse_relationship():
    m = _model("sample_entities.har")
    assert _rel(m, "Patient", "Visit") is not None   # visits in the patient detail response


def test_path_relationship_customer_order():
    m = _model("sample_flow.har")
    r = _rel(m, "Customer", "Order")          # /api/customers/1001/orders and Order.customerId
    assert r is not None
    assert r.kind in {"path", "foreign_key"} and r.confidence == "High"


def test_rows_stay_aligned():
    m = _model("sample_entities.har")
    patients = m.instances["Patient"]
    by_id = {str(row["patientId"]): row for row in patients}
    # patient 1 must keep ITS name and ward, never a scrambled pairing
    assert by_id["1"]["patientName"] == "Asha" and by_id["1"]["wardId"] == 10
    assert by_id["2"]["patientName"] == "Ravi" and by_id["2"]["wardId"] == 11


def test_rows_merge_across_list_and_detail():
    # patient 1 appears in the list (with wardId) and the detail (with dob) → one merged, aligned row
    m = _model("sample_entities.har")
    row1 = next(r for r in m.instances["Patient"] if str(r["patientId"]) == "1")
    assert row1.get("wardId") == 10 and row1.get("dob") == "2001-07-03"


def test_topological_order_parents_before_children():
    m = _model("sample_entities.har")
    order = m.ordered_entities
    assert order.index("Ward") < order.index("Patient")     # Ward parents Patient
    assert order.index("Patient") < order.index("Visit")    # Patient parents Visit


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
