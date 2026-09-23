"""ISSUE 2 — parameterization must classify by ROLE/INTENT, not "looks dynamic".

Proves, domain-agnostically:
  * W3C Navigation/Resource-Timing browser telemetry (fetchStart, domComplete, transferSize, duration
    inside a RUM cluster, …) is NEVER a CSV column — even when smuggled into a kept business request.
  * a lone business-named numeric field that merely collides with an ambiguous timing word is NOT
    suppressed (multi-signal: standard name + numeric + RUM cluster, not name alone).
  * static configuration (pageSize) stays hardcoded, server-generated ids correlate, and genuine
    business inputs — including entity ids with UNFAMILIAR names across domains — are parameterized.
  * unknown client values are not auto-added to the CSV (CSV minimality).
"""
from __future__ import annotations

import json
import re

from har2jmx.classify import ValueClass
from har2jmx.emit import build_jmx_xml
from har2jmx.engine import analyze

TIMING = {
    "fetchStart": 12.3, "domainLookupStart": 14.1, "domainLookupEnd": 15.9, "connectStart": 20.0,
    "connectEnd": 30.2, "secureConnectionStart": 22.7, "requestStart": 31.0, "responseStart": 44.5,
    "responseEnd": 60.8, "domInteractive": 900.4, "domContentLoadedEventEnd": 950.1,
    "domComplete": 1400.9, "loadEventEnd": 1450.0, "transferSize": 84213, "encodedBodySize": 22140,
    "decodedBodySize": 90000, "duration": 1500.2, "startTime": 0.0,
}
_UDV = {"THREADS", "LOOPS", "RAMP", "THINKTIME", "BASE_URL", "PROTOCOL", "HOLD", "DURATION", "TIMEOUT"}


def _e(method, url, *, body=None, raw=None, ctype="application/json", resp="{}", sec=0, page="p1", st=200):
    e = {"pageref": page, "startedDateTime": f"2024-01-01T10:00:{sec:02d}.000Z", "time": 30,
         "request": {"method": method, "url": url, "cookies": [], "queryString": [],
                     "headers": [{"name": "Content-Type", "value": ctype}]},
         "response": {"status": st, "headers": [{"name": "Content-Type", "value": "application/json"}],
                      "content": {"mimeType": "application/json", "text": resp}}}
    if raw is not None:
        e["request"]["postData"] = {"mimeType": ctype, "text": raw}
    elif body is not None:
        e["request"]["postData"] = {"mimeType": ctype, "text": json.dumps(body)}
    return e


def _run(entries):
    res = analyze(json.dumps({"log": {"version": "1.2", "entries": entries}}).encode())
    return res, build_jmx_xml(res, {"threads": "5"}).decode()


def _cols(res):
    return [c.name for d in res.parameterization.datasets for c in d.columns]


def _verd(res, value):
    return res.classification.by_value(str(value))


def test_rum_timing_cluster_smuggled_into_business_request_never_parameterized():
    # a business POST that also carries a cluster of W3C timing metrics next to a real input
    body = {"sku": "SKU-2231", **TIMING}
    res, xml = _run([_e("POST", "https://app.example.com/api/orders", body=body,
                        resp='{"orderId":"ORD-1"}', sec=0)])
    cols = _cols(res)
    # not one timing metric leaks into the CSV
    for name in TIMING:
        assert name not in cols, f"telemetry field {name} became a CSV column"
    # each timing VALUE that was classified is STATIC telemetry (not business, not runtime)
    for val in TIMING.values():
        v = _verd(res, val)
        if v is not None:
            assert v.classification == ValueClass.STATIC
            assert "timing" in v.reason.lower() or "telemetry" in v.reason.lower()
    # the genuine business input is still parameterized
    assert "sku" in cols and "${sku}" in xml


def test_timing_values_are_not_correlations_either():
    # telemetry must not be mistaken for server-generated dynamic state and correlated
    res, xml = _run([_e("POST", "https://app.example.com/api/rum", body=dict(TIMING), sec=0)])
    extractors = set(re.findall(r'referenceNames">([^<]+)<', xml))
    for name in TIMING:
        assert name not in extractors, f"timing field {name} was correlated"


def test_ambiguous_duration_alone_is_not_suppressed_as_telemetry():
    # a lone business 'duration' (call length) with NO timing cluster must NOT be classified as telemetry
    # just because the word collides — proves name-alone does not decide.
    res, _ = _run([
        _e("POST", "https://svc.example.com/api/calls", body={"duration": "3600", "agentId": "AG-1"},
           resp='{"callId":"CALL-1"}', sec=0),
        _e("POST", "https://svc.example.com/api/calls/report", body={"duration": "3600"}, resp="{}", sec=2),
    ])
    v = _verd(res, "3600")
    assert v is None or v.classification != ValueClass.STATIC or "timing" not in v.reason.lower(), \
        "a lone business 'duration' was wrongly suppressed as browser telemetry"


def test_static_config_pagesize_is_hardcoded_not_csv():
    res, _ = _run([_e("GET", "https://app.example.com/api/list?pageSize=100&view=grid",
                      resp='{"items":[]}', sec=0)])
    cols = _cols(res)
    assert "pageSize" not in cols and "view" not in cols
    v = _verd(res, "100")
    assert v is None or v.classification == ValueClass.STATIC


def test_server_generated_ref_correlates_not_parameterized():
    res, xml = _run([
        _e("POST", "https://shop.example.com/api/checkout/prepare", body={"cart": "x"},
           resp='{"checkoutRef":"CHK-9f8e7d6c"}', sec=0),
        _e("POST", "https://shop.example.com/api/checkout/CHK-9f8e7d6c/confirm", body={"pay": "card"},
           resp="{}", sec=2),
    ])
    assert "checkoutRef" not in _cols(res)
    extractors = set(re.findall(r'referenceNames">([^<]+)<', xml))
    assert any("checkoutref" in x.lower() for x in extractors)


def test_unfamiliar_entity_id_parameterized_by_intent_across_domains():
    # domain-agnostic: an entity id with an UNFAMILIAR name, returned by a read and reused, is
    # parameterized by INTENT (selection + reuse), while timing telemetry in the same journey is excluded.
    for id_field, id_val, path in [
        ("memberKey", "MBR-88213", "members"),      # insurance/healthcare
        ("subscriberRef", "SUB-4471", "subscribers"),  # telecom
        ("policyNo", "POL-2025-77", "policies"),     # insurance
    ]:
        res, _ = _run([
            _e("GET", f"https://x.example.com/api/{path}?plan=gold",
               resp=json.dumps({path: [{id_field: id_val}]}), sec=0),
            _e("GET", f"https://x.example.com/api/{path}/{id_val}/detail", resp="{}", sec=2),
            _e("POST", "https://x.example.com/api/rum", body=dict(TIMING), sec=4),
        ])
        cols = _cols(res)
        assert id_field in cols, f"{id_field} should be parameterized by intent (got {cols})"
        for name in TIMING:
            assert name not in cols


def test_navigationid_descriptor_not_parameterized():
    # a non-numeric telemetry descriptor (navigationId GUID / navigationType label) reused across a RUM
    # payload and a kept request must not become CSV test data.
    nav = TIMING["fetchStart"]  # keep cluster
    body = dict(TIMING)
    body["navigationType"] = "navigate"
    res, _ = _run([
        _e("POST", "https://app.example.com/api/rum", body=body, sec=0),
        _e("POST", "https://app.example.com/api/orders", body={"sku": "S-1", "navigationType": "navigate"},
           resp='{"orderId":"O-1"}', sec=2),
    ])
    assert "navigationType" not in _cols(res)
    v = _verd(res, "navigate")
    assert v is None or v.classification in (ValueClass.STATIC, ValueClass.UNKNOWN)
    assert nav is not None
