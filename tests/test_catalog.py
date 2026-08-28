"""Correlation catalog + structural entity detection across a mixed enterprise flow.

Exercises pagination/continuation tokens, ETag/version locks, created object ids, and structural
entity detection (Patient / Appointment) with a foreign-key relationship — none name-listed.
"""
from __future__ import annotations

from pathlib import Path

from har2jmx.classify import ValueClass
from har2jmx.engine import analyze

FIX = Path(__file__).parent / "fixtures"


def _res():
    return analyze((FIX / "sample_catalog.har").read_bytes())


def _corr(r):
    return {c.variable: c for c in r.correlations}


def test_continuation_token_correlated():
    assert "nextPageToken" in _corr(_res())          # pagination/continuation token


def test_etag_version_lock_correlated():
    r = _res()
    c = _corr(r).get("ETag")
    assert c is not None and c.extractor.value == "regex"   # from response header, replayed as If-Match
    # and never left as test data
    dataset_values = {v for d in r.parameterization.datasets for row in d.rows for v in row.values()}
    assert '"ver-3-a1b2c3d4"' not in dataset_values


def test_created_object_id_correlated():
    c = _corr(_res()).get("appointmentId")
    assert c is not None and c.value == "APPT-7788"


def test_entities_detected_structurally_with_relationship():
    r = _res()
    names = {e.name for e in r.entities_model.entities}
    assert {"Patient", "Appointment"} <= names       # discovered from structure, not a name list
    rels = {(x.parent, x.child) for x in r.entities_model.relationships}
    assert ("Patient", "Appointment") in rels        # appointment references patient


def test_existing_ids_are_parameters_not_correlations():
    r = _res()
    by_value = {v.value: v.classification for v in r.classification.verdicts}
    assert by_value.get("PAT-9001") == ValueClass.BUSINESS_MASTER_DATA   # existing patient → parameter


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for fn in fns:
        try:
            fn()
        except AssertionError as e:
            print(f"FAIL  {fn.__name__}: {e}")
        except Exception as e:
            print(f"ERROR {fn.__name__}: {type(e).__name__}: {e}")
        else:
            passed += 1
            print(f"ok    {fn.__name__}")
    print(f"\n{passed}/{len(fns)} passed")
    raise SystemExit(0 if passed == len(fns) else 1)
