"""Milestone 2 tests — request noise classification.

Runs under pytest, and also directly:  PYTHONPATH=src python tests/test_request_noise.py
"""
from __future__ import annotations

from pathlib import Path

from har2jmx.classify import build_request_classification_report, classify_capture
from har2jmx.ir.build import build_capture
from har2jmx.ir.normalized import RequestRole

FIX = Path(__file__).parent / "fixtures"


def _cap(name: str):
    cap = build_capture((FIX / name).read_bytes())
    classify_capture(cap)
    return cap


def test_roles_on_mixed_capture():
    r = _cap("sample_mini.har").requests
    assert r[0].classification.role == RequestRole.AUTH       # /api/authenticate
    assert r[1].classification.role == RequestRole.BUSINESS   # /api/patients (GET json)
    assert r[2].classification.role == RequestRole.STATIC     # logo.svg
    assert r[3].classification.role == RequestRole.TELEMETRY  # /eum/beacon
    assert r[4].classification.role == RequestRole.BUSINESS   # graphql
    assert r[5].classification.role == RequestRole.AUTH       # /connect/authorize


def test_static_and_telemetry_are_excluded_but_kept():
    cap = _cap("sample_mini.har")
    svg = cap.requests[2]
    beacon = cap.requests[3]
    assert svg.classification.excluded and svg.classification.static_candidate
    assert beacon.classification.excluded and beacon.classification.telemetry_candidate
    # nothing deleted — every entry still present
    assert cap.count == 6


def test_business_and_auth_not_excluded():
    r = _cap("sample_mini.har").requests
    assert not r[0].classification.excluded  # auth is business-relevant
    assert not r[1].classification.excluded
    assert not r[4].classification.excluded


def test_preflight_head_telemetry_static_excluded():
    r = _cap("sample_noise.har").requests
    assert r[0].classification.excluded and "preflight" in r[0].classification.exclusion_reason.lower()
    assert r[1].classification.excluded and "head" in r[1].classification.exclusion_reason.lower()
    assert r[2].classification.role == RequestRole.TELEMETRY and r[2].classification.excluded  # GA host
    assert r[3].classification.role == RequestRole.STATIC and r[3].classification.excluded     # .css


def test_upload_download_tagged_not_excluded():
    r = _cap("sample_noise.har").requests
    assert r[4].classification.role == RequestRole.UPLOAD and not r[4].classification.excluded
    assert r[5].classification.role == RequestRole.DOWNLOAD and not r[5].classification.excluded


def test_polling_detected():
    r = _cap("sample_noise.har").requests
    poll = r[6:10]
    assert all(x.classification.polling_candidate for x in poll)
    assert all(x.classification.role == RequestRole.POLLING for x in poll)
    assert all(not x.classification.excluded for x in poll)  # polling is business-relevant


def test_business_write_is_business():
    r = _cap("sample_noise.har").requests
    assert r[10].classification.role == RequestRole.BUSINESS  # POST /api/orders 201


def test_summary_counts_and_report():
    cap = _cap("sample_noise.har")
    summary = classify_capture(cap)
    # excluded = OPTIONS + HEAD + GA telemetry + css static = 4
    assert summary.excluded == 4
    assert summary.total == 11
    report = build_request_classification_report(cap)
    assert "Request Classification Report" in report
    assert "Excluded requests" in report


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
