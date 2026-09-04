"""Extractor self-check — resolve each emitted extractor against its captured response.

Guards the silent-wrong-on-a-real-app failure mode: a $..leaf extractor with match_number=1 that
matches the wrong node, or a pattern that no longer resolves, shipping as a false-green ${var}.
"""
from __future__ import annotations

from pathlib import Path

from har2jmx.classify import classify_capture
from har2jmx.emit import build_jmx_xml
from har2jmx.engine import analyze
from har2jmx.ir.build import build_capture
from har2jmx.validate import ExtractorStatus, verify_extractors
from har2jmx.webreport import assess_capture_quality, build_manual_correlations

FIX = Path(__file__).parent / "fixtures"


def _check(result, variable: str):
    return next((c for c in result.extractor_checks if c.variable == variable), None)


def test_unique_extractor_verified_and_shipped_as_is():
    # a clean created id lives at exactly one node → UNIQUE, shipped as $..orderId with its assertion.
    result = analyze((FIX / "sample_flow.har").read_bytes())
    chk = _check(result, "orderId")
    assert chk is not None and chk.status == ExtractorStatus.UNIQUE
    x = build_jmx_xml(result).decode()
    assert "$..orderId" in x
    assert 'testname="Assert orderId correlated"' in x


def test_ambiguous_extractor_refined_to_concrete_object_path():
    # the create-response echoes the new order AND a list of prior orders (three orderId nodes). The
    # recorded value sits at the stable object path order.orderId → the extractor is pinned there so
    # match #1 can't grab a prior order under load.
    result = analyze((FIX / "sample_ambiguous_id.har").read_bytes())
    chk = _check(result, "orderId")
    assert chk is not None, "expected an orderId correlation"
    assert chk.status == ExtractorStatus.AMBIGUOUS_REFINED
    assert chk.refined_expression == "$.order.orderId"
    x = build_jmx_xml(result).decode()
    assert "$.order.orderId" in x            # concrete, unambiguous path emitted
    assert "$..orderId" not in x             # the ambiguous recursive form is not shipped
    assert "${orderId}" in x                 # value still correlated (path uses the variable)
    assert "ORD-NEW-777" not in x            # the live value never ships as a literal
    assert "ORD-OLD-001" not in x            # a prior order is never mistaken for the created one


def test_unresolved_extractor_dropped_and_escalated():
    # the created id sits inside a per-run list (orders[0]) alongside another orderId → no stable
    # JSONPath selects it. The extractor must be dropped (not a false green) and the value escalated
    # to the manual-review list, shipping as a literal.
    result = analyze((FIX / "sample_list_id.har").read_bytes())
    chk = _check(result, "orderId")
    assert chk is not None and chk.status == ExtractorStatus.UNRESOLVED
    x = build_jmx_xml(result).decode()
    assert 'referenceNames">orderId<' not in x     # no JSON extractor for the unresolved value
    assert "${orderId}" not in x                    # not substituted anywhere (would be NOT_FOUND)
    assert "ORD-NEW-9" in x                          # ships as the recorded literal instead
    manual = build_manual_correlations(result)
    assert any("ORD" in m["value"] or "9" in m["value"] for m in manual), "value not escalated"
    assert any("list" in m["reason"].lower() for m in manual), "reason should explain the list ambiguity"


def test_verify_extractors_is_pure_and_covers_only_noncookie():
    # cookie-manager correlations have no explicit extractor to verify → not represented as checks.
    result = analyze((FIX / "sample_lineage.har").read_bytes())
    checks = verify_extractors(result.capture, result.correlations)
    assert all(c.extractor.value != "cookie_manager" for c in checks)
    # every check refers to a real producing request index
    idxs = {r.context.index for r in result.capture.requests}
    assert all(c.producer_index in idxs for c in checks)


def test_capture_quality_flags_bodyless_capture():
    full = analyze((FIX / "sample_flow.har").read_bytes())
    q_full = assess_capture_quality(full.capture)
    assert q_full["bodyCoveragePct"] >= 75 and not q_full["degraded"]

    # a capture recorded without response bodies → degraded, and the count is surfaced
    har = {"log": {"version": "1.2", "entries": [
        {"startedDateTime": "2026-01-01T10:00:00.000Z", "time": 20,
         "request": {"method": "POST", "url": "https://x.example.com/api/a",
                     "headers": [{"name": "Content-Type", "value": "application/json"}], "cookies": [],
                     "postData": {"mimeType": "application/json", "text": "{\"k\":\"v\"}"}},
         "response": {"status": 200, "headers": [], "content": {"mimeType": "application/json", "text": ""}}},
        {"startedDateTime": "2026-01-01T10:00:01.000Z", "time": 20,
         "request": {"method": "POST", "url": "https://x.example.com/api/b",
                     "headers": [{"name": "Content-Type", "value": "application/json"}], "cookies": [],
                     "postData": {"mimeType": "application/json", "text": "{\"k\":\"v\"}"}},
         "response": {"status": 200, "headers": [], "content": {"mimeType": "application/json", "text": ""}}},
    ]}}
    cap = build_capture(har)
    classify_capture(cap)
    q = assess_capture_quality(cap)
    assert q["emptyBodies"] >= 1
    assert q["degraded"] is True


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
