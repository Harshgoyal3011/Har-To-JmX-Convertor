"""Cursor / continuation-token pagination — each page's cursor must be correlated, not hardcoded."""
from __future__ import annotations

from pathlib import Path

from har2jmx.emit import build_jmx_xml
from har2jmx.emit.validate import validate_plan
from har2jmx.engine import analyze

FIX = Path(__file__).parent / "fixtures"


def _result():
    return analyze((FIX / "sample_pagination.har").read_bytes())


def test_continuation_cursor_is_correlated_not_parameterized():
    # nextCursor is opaque server state pointing at the next page — a recorded value is valid only for
    # that dataset snapshot, so it must be extracted per page, never sat in a static CSV.
    r = _result()
    by_var = {c.variable: c.value for c in r.correlations}
    assert by_var.get("nextCursor") == "CUR-aaa111"     # from page 1's response
    assert by_var.get("nextCursor2") == "CUR-bbb222"    # from page 2's response
    # it must NOT have leaked into a parameter dataset
    for d in r.parameterization.datasets:
        for col in d.columns:
            assert "cursor" not in col.name.lower()


def test_each_page_sends_the_extracted_cursor():
    r = _result()
    x = build_jmx_xml(r).decode()
    # page 2 sends the cursor extracted from page 1; page 3 the one from page 2
    assert "cursor</stringProp>" in x
    assert "${nextCursor}" in x and "${nextCursor2}" in x
    # the recorded cursor values never ship as literals
    assert "CUR-aaa111" not in x and "CUR-bbb222" not in x


def test_pagination_plan_is_production_clean():
    r = _result()
    assert validate_plan(r, build_jmx_xml(r).decode()) == []


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
