"""Complex-scenario tests — GraphQL (operation-named transactions, variables-only params)."""
from __future__ import annotations

from pathlib import Path

from har2jmx.engine import analyze

FIX = Path(__file__).parent / "fixtures"


def _res():
    return analyze((FIX / "sample_graphql.har").read_bytes())


def test_graphql_detected():
    assert "GraphQL" in {d.name for d in _res().application.api_styles}


def test_transactions_named_from_operation():
    names = [t.name for t in _res().transactions]
    assert names == ["List Products", "Search Products"]


def test_only_variables_parameterized_not_envelope():
    datasets = _res().parameterization.datasets
    cols = {c.name for d in datasets for c in d.columns}
    assert "term" in cols                       # the GraphQL variable is a business input
    assert "operationName" not in cols          # protocol envelope excluded
    assert "query" not in cols


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
