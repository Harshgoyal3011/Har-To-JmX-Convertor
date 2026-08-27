"""Milestone 11 tests — replay validator."""
from __future__ import annotations

from pathlib import Path

from har2jmx.classify import classify_capture
from har2jmx.correlate import CorrelationDecision, ExtractorType, build_correlations
from har2jmx.ir.build import build_capture
from har2jmx.parameterize import ParameterColumn, ParameterDataset, build_parameterization
from har2jmx.validate import validate_replay

FIX = Path(__file__).parent / "fixtures"


def _ctx(name: str):
    cap = build_capture((FIX / name).read_bytes())
    classify_capture(cap)
    return cap, build_correlations(cap), build_parameterization(cap)


def _find(report, check):
    return next(f for f in report.findings if f.check == check)


def test_clean_flow_passes():
    cap, corr, plan = _ctx("sample_flow.har")
    r = validate_replay(cap, corr, plan)
    assert r.passed
    assert _find(r, "No runtime value placed in a dataset").passed
    assert _find(r, "No master data correlated").passed
    assert _find(r, "No variable consumed before extraction").passed


def test_detects_runtime_value_in_dataset():
    cap, corr, plan = _ctx("sample_flow.har")
    # inject the created order id (a runtime value) into a dataset — this must be caught as CRITICAL
    plan.datasets.append(ParameterDataset(
        name="BadOrders", columns=[ParameterColumn(name="orderId", sample="ORD1", entity_field="orderId")],
        rows=[{"orderId": "ORD1"}], source="entity",
    ))
    r = validate_replay(cap, corr, plan)
    f = _find(r, "No runtime value placed in a dataset")
    assert not f.passed and f.severity == "CRITICAL"
    assert not r.passed


def test_detects_master_data_correlated():
    cap, corr, plan = _ctx("sample_flow.har")
    corr.append(CorrelationDecision(
        variable="customerId", value="1001", producer_index=3,
        producer_location="response.body:id", extractor=ExtractorType.JSON,
        expression="$..id", consumers=[7], confidence="High",
    ))
    r = validate_replay(cap, corr, plan)
    f = _find(r, "No master data correlated")
    assert not f.passed and f.severity == "HIGH"


def test_single_row_dataset_flagged_low():
    cap, corr, plan = _ctx("sample_flow.har")
    r = validate_replay(cap, corr, plan)
    f = _find(r, "Distinct data available per iteration")
    assert not f.passed and f.severity == "LOW"   # Customer dataset has a single row
    assert r.passed                                # LOW does not fail the gate


def test_score_bounds():
    cap, corr, plan = _ctx("sample_flow.har")
    r = validate_replay(cap, corr, plan)
    assert 0 <= r.score <= 100


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
