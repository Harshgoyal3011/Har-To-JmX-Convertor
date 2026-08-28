"""Milestone 12 tests — engine orchestration & metrics (end-to-end)."""
from __future__ import annotations

from pathlib import Path

from har2jmx.engine import analyze

FIX = Path(__file__).parent / "fixtures"
ALL = ["sample_mini.har", "sample_noise.har", "sample_auth_stack.har", "sample_flow.har",
       "sample_entities.har", "sample_lineage.har", "sample_params.har"]


def _res(name: str):
    return analyze((FIX / name).read_bytes())


def test_end_to_end_flow():
    r = _res("sample_flow.har")
    assert any(c.variable == "orderId" for c in r.correlations)          # created id correlated
    assert any(d.name == "Customer" for d in r.parameterization.datasets)  # existing entity parameterized
    assert r.replay.passed
    assert [t.name for t in r.transactions][:1] == ["Login"]


def test_metrics_are_present_and_bounded():
    r = _res("sample_flow.har")
    m = r.metrics
    assert m["requests"]["total"] == 10
    assert m["correlation"]["count"] >= 1
    assert 0 <= m["replay_readiness"] <= 100
    assert m["parameterization"]["datasets"] >= 1
    assert "_estimated" in m and m["_estimated"]        # estimates are labelled, not hidden


def test_all_fixtures_analyze_without_error():
    for name in ALL:
        r = _res(name)
        assert 0 <= r.metrics["replay_readiness"] <= 100
        assert r.metrics["requests"]["total"] == r.capture.count


def test_noise_capture_has_no_correlations_or_datasets():
    # pure noise/CRUD with no reused runtime values or business master data
    r = _res("sample_noise.har")
    assert r.correlations == []
    assert r.metrics["requests"]["excluded"] >= 4       # OPTIONS/HEAD/telemetry/static excluded


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
