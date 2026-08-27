"""Milestone 9 tests — lifecycle-aware correlation engine."""
from __future__ import annotations

from pathlib import Path

from har2jmx.classify import classify_capture
from har2jmx.correlate import ExtractorType, build_correlations
from har2jmx.ir.build import build_capture

FIX = Path(__file__).parent / "fixtures"


def _corr(name: str):
    cap = build_capture((FIX / name).read_bytes())
    classify_capture(cap)
    decisions = build_correlations(cap)
    return {d.variable: d for d in decisions}, decisions


def test_created_id_gets_json_extractor():
    by_var, _ = _corr("sample_flow.har")
    assert "orderId" in by_var
    d = by_var["orderId"]
    assert d.extractor == ExtractorType.JSON
    assert d.expression in ("$.orderId", "$..orderId")
    assert d.consumers and d.value == "ORD1"


def test_master_data_id_is_not_correlated():
    by_var, _ = _corr("sample_flow.har")
    # customer 1001 is existing master data → must NOT be a correlation
    assert all(d.value != "1001" for d in by_var.values())


def test_session_cookie_uses_cookie_manager():
    by_var, _ = _corr("sample_lineage.har")
    assert "AUTH" in by_var
    assert by_var["AUTH"].extractor == ExtractorType.COOKIE_MANAGER   # replayed via Cookie Manager
    assert by_var["AUTH"].value == "SID-abc123def"


def test_runtime_userid_json_extractor():
    by_var, _ = _corr("sample_lineage.har")
    assert "userId" in by_var and by_var["userId"].extractor == ExtractorType.JSON


def test_no_extractor_without_consumer_and_no_duplicates():
    _, decisions = _corr("sample_flow.har")
    assert all(d.consumers for d in decisions)                # every extractor has a consumer
    keys = [(d.variable, d.value) for d in decisions]
    assert len(keys) == len(set(keys))                        # no duplicates


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
