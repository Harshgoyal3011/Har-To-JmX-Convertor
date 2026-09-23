"""Part 13 — failure injection: prove the release gates are NOT a rubber stamp.

Start from a known-good generated JMX, inject each defect, and assert the corresponding gate flips to
FAIL. The unmodified artifact must pass every gate.
"""
from __future__ import annotations

import json
import re

import pytest

from har2jmx.emit import build_jmx_xml
from har2jmx.engine import analyze
from release_gate import determinism_gate, evaluate


def _e(method, url, *, hdr=None, body=None, raw=None, ctype="application/json", resp="{}",
       rmime="application/json", set_cookie=None, status=None, sec=0, page="p1"):
    H = [{"name": "Content-Type", "value": ctype}, {"name": "Accept", "value": "application/json"}]
    for k, v in (hdr or {}).items():
        H.append({"name": k, "value": v})
    rh = [{"name": "Content-Type", "value": rmime}]
    if set_cookie:
        rh.append({"name": "Set-Cookie", "value": set_cookie})
    if status is None:
        status = 201 if (method == "POST" and url.rstrip("/").endswith("orders")) else 200
    ent = {"pageref": page, "startedDateTime": f"2024-01-01T10:00:{sec:02d}.000Z", "time": 50,
           "request": {"method": method, "url": url, "httpVersion": "HTTP/1.1", "headers": H,
                       "queryString": [], "cookies": []},
           "response": {"status": status, "headers": rh, "cookies": [],
                        "content": {"mimeType": rmime, "text": resp}}}
    if raw is not None:
        ent["request"]["postData"] = {"mimeType": ctype, "text": raw}
    elif body is not None:
        ent["request"]["postData"] = {"mimeType": ctype, "text": json.dumps(body)}
    return ent


def _base():
    entries = [
        _e("POST", "https://app.example.com/api/login", ctype="application/x-www-form-urlencoded",
           raw="signInName=perfSuperuser%40mailinator.com&password=Aug%402026",
           set_cookie="JSESSIONID=sess-abc-123; Path=/", resp='{"access_token":"TKN-987"}', sec=0, page="p1"),
        _e("GET", "https://maps.googleapis.com/maps/api/js?key=K", rmime="text/javascript", sec=6, page="p2"),
        _e("GET", "https://app.example.com/assets/app.css", rmime="text/css", sec=6, page="p2"),
        _e("GET", "https://app.example.com/api/customers?q=acme", hdr={"Authorization": "Bearer TKN-987"},
           resp='{"customers":[{"customerId":"CUST-9","name":"Acme"}]}', sec=6, page="p2"),
        _e("POST", "https://app.example.com/api/orders", hdr={"Authorization": "Bearer TKN-987"},
           body={"item": "widget"}, resp='{"orderId":"ORD-77"}', sec=12, page="p3"),
        _e("GET", "https://app.example.com/api/orders/ORD-77", hdr={"Authorization": "Bearer TKN-987"},
           resp='{"orderId":"ORD-77"}', sec=14, page="p3"),
    ]
    res = analyze(json.dumps({"log": {"version": "1.2", "entries": entries}}).encode())
    xml = build_jmx_xml(res, {"threads": "5", "thinktime": "800"}).decode()
    return res, xml


def _gate(res, xml, name):
    for gr in evaluate(res, xml):
        if gr.name == name:
            return gr
    raise AssertionError(f"gate not found: {name}")


def _fails(res, xml, name):
    return not _gate(res, xml, name).passed


# ---- the clean artifact passes everything --------------------------------------------------------

def test_clean_artifact_passes_all_gates():
    res, xml = _base()
    failed = [gr.name for gr in evaluate(res, xml) if not gr.passed]
    assert not failed, f"clean artifact unexpectedly failed: {failed}"


# ---- each injected defect must flip its gate to FAIL ---------------------------------------------

def test_inject_thread_group_assertion():
    res, xml = _base()
    inj = ('<ResponseAssertion testname="Assert Response Code (2xx/3xx)"><stringProp '
           'name="Assertion.test_field">Assertion.response_code</stringProp></ResponseAssertion><hashTree/>')
    # insert right after the ThreadGroup's own hashTree opens
    bad = re.sub(r'(</ThreadGroup>\s*<hashTree>)', r'\1' + inj, xml, count=1)
    assert bad != xml
    assert _fails(res, bad, "no Thread-Group response assertion")


_ASSERT_BLOCK = r'<ResponseAssertion [^>]*testname="Assert Response Code \(2xx/3xx\)"[^>]*>.*?</ResponseAssertion>\s*<hashTree/>'


def test_inject_remove_a_transaction_assertion():
    res, xml = _base()
    bad = re.sub(_ASSERT_BLOCK, "", xml, count=1, flags=re.S)
    assert bad != xml
    assert _fails(res, bad, "exactly one assertion per Transaction Controller")


def test_inject_extra_assertion_duplication():
    res, xml = _base()
    m = re.search(_ASSERT_BLOCK, xml, re.S)
    bad = xml[:m.end()] + m.group(0) + xml[m.end():]        # duplicate one assertion block
    assert _fails(res, bad, "no per-sampler assertion duplication")


def test_inject_maps_sampler():
    res, xml = _base()
    bad = re.sub(r'(name="HTTPSampler\.path">)/api/customers(<)',
                 r'\g<1>/maps/api/js\2', xml, count=1)     # a sampler now points at the excluded maps path
    assert bad != xml
    assert _fails(res, bad, "no excluded request path became a sampler")


def test_inject_static_sampler():
    res, xml = _base()
    bad = re.sub(r'(name="HTTPSampler\.path">)/api/customers(<)',
                 r'\g<1>/assets/app.css\2', xml, count=1)
    assert bad != xml
    assert _fails(res, bad, "no static asset sampler")


def test_inject_unused_csv_column():
    res, xml = _base()
    bad = re.sub(r'(variableNames">)', r'\1ghostColumn,', xml, count=1)
    assert bad != xml
    assert _fails(res, bad, "every CSV column referenced by a ${var}")


def test_inject_unresolved_variable():
    res, xml = _base()
    bad = re.sub(r'(name="HTTPSampler\.path">/api/customers)(<)', r'\1/${ghostVar}\2', xml, count=1)
    assert bad != xml
    # validate_plan flags an unresolved variable with no CSV/extractor/UDV source
    assert _fails(res, bad, "validate_plan clean (no unresolved vars / leaks / unused CSV)")


def test_determinism_gate_detects_nondeterminism(monkeypatch):
    # inject non-determinism by making the plan name vary, then prove the determinism gate catches it
    import har2jmx.emit.jmx as jmxmod
    orig = jmxmod._build_jmx_tree
    counter = {"n": 0}

    def flaky(result, config=None, csv_files=None):
        counter["n"] += 1
        out = orig(result, config, csv_files)
        return out.replace(b"har2jmx Plan", b"har2jmx Plan " + str(counter["n"]).encode())

    monkeypatch.setattr(jmxmod, "_build_jmx_tree", flaky)
    import json as _j
    har = _j.dumps({"log": {"version": "1.2", "entries": [
        _e("POST", "https://app.example.com/api/orders", body={"item": "x"}, resp='{"orderId":"O-1"}')]}}).encode()
    gr = determinism_gate(har)
    assert not gr.passed        # two runs now differ -> gate FAILS as intended
