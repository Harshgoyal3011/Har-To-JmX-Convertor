"""Milestone 5 tests — business entity discovery.

Runs under pytest, and also directly:  PYTHONPATH=src python tests/test_entities.py
"""
from __future__ import annotations

from pathlib import Path

from har2jmx.classify import classify_capture
from har2jmx.entities import discover_entities
from har2jmx.ir.build import build_capture

FIX = Path(__file__).parent / "fixtures"


def _entities(name: str):
    cap = build_capture((FIX / name).read_bytes())
    classify_capture(cap)
    return {e.name: e for e in discover_entities(cap)}


def test_entities_discovered_from_structure():
    ents = _entities("sample_entities.har")
    assert {"Patient", "Ward", "Visit"} <= set(ents)


def test_identifiers_detected():
    ents = _entities("sample_entities.har")
    assert ents["Patient"].identifier == "patientId"
    assert ents["Ward"].identifier == "id"
    assert ents["Visit"].identifier == "visitId"


def test_attributes_grouped_under_entity():
    ents = _entities("sample_entities.har")
    patient_attrs = {a.name for a in ents["Patient"].attributes}
    assert {"patientId", "patientName", "wardId", "dob"} <= patient_attrs
    ward_attrs = {a.name for a in ents["Ward"].attributes}
    assert {"id", "name"} <= ward_attrs


def test_instance_counts_and_confidence():
    ents = _entities("sample_entities.har")
    assert ents["Patient"].instance_count == 2   # patientId 1 and 2
    assert ents["Ward"].instance_count == 2       # id 10 and 11
    assert ents["Patient"].confidence == "High"   # id + >=3 attrs + >=2 instances
    for e in ents.values():
        assert e.evidence  # every entity is evidence-backed


def test_wrappers_and_tokens_are_not_entities():
    # envelope keys (status/data) and single-scalar token payloads must not become entities.
    ents = _entities("sample_entities.har")
    assert "Status" not in ents and "Data" not in ents and "Result" not in ents
    flow = _entities("sample_flow.har")
    assert "Token" not in flow and "Authenticate" not in flow


def test_flow_capture_yields_customer_and_order():
    ents = _entities("sample_flow.har")
    assert "Customer" in ents
    assert "Order" in ents
    assert ents["Order"].identifier == "orderId"


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
