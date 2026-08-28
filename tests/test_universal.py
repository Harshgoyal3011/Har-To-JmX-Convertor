"""Universality tests — decisions must be behavior-driven, not field-name-driven.

The same product identity is written six ways (productId / product_id / ProductID / prodId / sku /
path segment). The engine must treat it as ONE parameter by value, and correlate the server-created
order id — regardless of naming convention. This is what makes the engine work on apps that don't
exist yet: it never depends on a dictionary of field names.
"""
from __future__ import annotations

from pathlib import Path

from har2jmx.classify import ValueClass
from har2jmx.engine import analyze

FIX = Path(__file__).parent / "fixtures"
PRODUCT = "SKU-88231-ALPHA"
ORDER = "ORD-5501-2026"


def _res():
    return analyze((FIX / "sample_naming.har").read_bytes())


def test_created_id_is_correlated_regardless_of_naming():
    r = _res()
    assert any(c.value == ORDER for c in r.correlations)       # server-created → correlate
    # and it never appears in a dataset
    dataset_values = {v for d in r.parameterization.datasets for row in d.rows for v in row.values()}
    assert ORDER not in dataset_values


def test_existing_value_is_one_parameter_across_six_spellings():
    r = _res()
    # productId / product_id / ProductID / prodId / sku / path all carry the SAME value —
    # it must be parameterized once, by value, not correlated.
    assert not any(c.value == PRODUCT for c in r.correlations)
    dataset_values = {v for d in r.parameterization.datasets for row in d.rows for v in row.values()}
    assert PRODUCT in dataset_values


def test_value_classification_is_behavioral():
    r = _res()
    by_value = {v.value: v.classification for v in r.classification.verdicts}
    assert by_value.get(ORDER) == ValueClass.RUNTIME_GENERATED
    assert by_value.get(PRODUCT) == ValueClass.BUSINESS_MASTER_DATA


def test_no_runtime_value_in_any_dataset():
    r = _res()
    runtime = {v.value for v in r.classification.verdicts if v.classification == ValueClass.RUNTIME_GENERATED}
    for d in r.parameterization.datasets:
        for row in d.rows:
            assert not (set(map(str, row.values())) & runtime), f"runtime value leaked into {d.name}"


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
