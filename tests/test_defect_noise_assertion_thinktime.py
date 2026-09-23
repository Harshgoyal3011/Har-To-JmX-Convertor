"""Regression tests for three targeted defect fixes:

1. Irrelevant third-party / browser traffic (maps, analytics, fonts, reCAPTCHA) must NOT become
   samplers — including when a widget loads as a *document*/iframe (which otherwise looks like a
   navigation) — while a required external dependency (an auth/identity provider) is preserved.
2. Exactly ONE response-code assertion per business transaction, placed INSIDE its Transaction
   Controller — never one global assertion at Thread Group level, never one per sampler.
3. Think time is emitted only BETWEEN Transaction Controllers — never inside a transaction and never
   before the first transaction.

The plan structure is validated against the actual emitted JMX tree (JMeter's element+hashTree
sibling layout), not just substring presence.
"""
from __future__ import annotations

import json
from xml.dom import minidom

from har2jmx.emit import build_jmx_xml
from har2jmx.engine import analyze


def _entry(method, url, mime, *, status=200, restype="", sfmode="", sfdest="",
           body=None, resp_body="", ts, page):
    headers = []
    if sfmode:
        headers.append({"name": "Sec-Fetch-Mode", "value": sfmode})
    if sfdest:
        headers.append({"name": "Sec-Fetch-Dest", "value": sfdest})
    e = {
        "_resourceType": restype, "pageref": page, "startedDateTime": ts, "time": 80,
        "request": {"method": method, "url": url, "httpVersion": "HTTP/1.1",
                    "headers": headers, "queryString": [], "cookies": [], "headersSize": -1, "bodySize": 0},
        "response": {"status": status, "statusText": "OK", "httpVersion": "HTTP/1.1",
                     "headers": [{"name": "Content-Type", "value": mime}], "cookies": [],
                     "content": {"size": len(resp_body), "mimeType": mime, "text": resp_body},
                     "redirectURL": "", "headersSize": -1, "bodySize": len(resp_body)},
        "cache": {}, "timings": {"send": 1, "wait": 40, "receive": 39},
    }
    if body is not None:
        e["request"]["postData"] = {"mimeType": "application/json", "text": json.dumps(body)}
    return e


def _mixed_capture_har() -> bytes:
    """A two-transaction journey with an external auth dependency plus browser/third-party noise —
    including maps/reCAPTCHA loaded as *iframes* (documents), the shape that previously leaked."""
    entries = [
        # --- Transaction 1: login via an EXTERNAL auth/identity provider (required dependency) ---
        _entry("GET", "https://app.example.com/login", "text/html", restype="document",
               sfmode="navigate", sfdest="document", resp_body="<html>login</html>",
               ts="2024-01-01T10:00:00.000Z", page="p1"),
        _entry("POST", "https://auth.identity-provider.com/oauth/token", "application/json",
               body={"username": "bob", "password": "pw"},
               resp_body='{"access_token":"AAA","account_id":"ACC-1"}',
               ts="2024-01-01T10:00:00.400Z", page="p1"),
        _entry("GET", "https://www.google-analytics.com/g/collect?v=2", "image/gif",
               restype="image", ts="2024-01-01T10:00:00.700Z", page="p1"),
        # --- Transaction 2: dashboard + create order, with third-party noise interleaved ---
        _entry("GET", "https://app.example.com/dashboard", "text/html", restype="document",
               sfmode="navigate", sfdest="document", resp_body="<html>dash</html>",
               ts="2024-01-01T10:00:12.000Z", page="p2"),
        # maps embedded as an IFRAME/document — looks like a navigation, still noise
        _entry("GET", "https://maps.googleapis.com/maps/embed/v1/place?q=NYC", "text/html",
               restype="sub_frame", sfmode="navigate", sfdest="document", resp_body="<html>map</html>",
               ts="2024-01-01T10:00:12.200Z", page="p2"),
        # reCAPTCHA iframe (document)
        _entry("GET", "https://www.google.com/recaptcha/api2/anchor?k=K", "text/html",
               restype="sub_frame", sfmode="navigate", sfdest="document", resp_body="<html>cap</html>",
               ts="2024-01-01T10:00:12.300Z", page="p2"),
        # maps geocode XHR (JSON — business-shaped, but third-party)
        _entry("GET", "https://maps.googleapis.com/maps/api/geocode/json?address=NYC", "application/json",
               restype="xhr", sfdest="empty", resp_body='{"results":[]}',
               ts="2024-01-01T10:00:12.400Z", page="p2"),
        _entry("POST", "https://app.example.com/api/orders", "application/json",
               body={"item": "x", "account_id": "ACC-1"}, resp_body='{"order_id":"9"}',
               ts="2024-01-01T10:00:12.600Z", page="p2"),
        # a font asset (third-party)
        _entry("GET", "https://fonts.gstatic.com/s/font.woff2", "font/woff2",
               restype="font", ts="2024-01-01T10:00:12.700Z", page="p2"),
    ]
    return json.dumps({"log": {"version": "1.2", "creator": {"name": "t", "version": "1"},
                               "entries": entries}}).encode()


# --------------------------------------------------------------------- JMX tree helpers

def _elems(node):
    return [c for c in node.childNodes if c.nodeType == c.ELEMENT_NODE]


def _collect(container, tag, out):
    """Collect (element, subtree_container) for every element of `tag` in JMeter's element+hashTree
    layout, recursing into each element's following hashTree sibling."""
    kids = _elems(container)
    i = 0
    while i < len(kids):
        e = kids[i]
        ht = kids[i + 1] if i + 1 < len(kids) and kids[i + 1].tagName == "hashTree" else None
        if e.tagName == "hashTree":
            _collect(e, tag, out)
            i += 1
            continue
        if e.tagName == tag:
            out.append((e, ht))
        if ht is not None:
            _collect(ht, tag, out)
        i += 2 if ht is not None else 1


def _thread_group_container(doc):
    tgs = []
    _collect(doc.documentElement, "ThreadGroup", tgs)
    assert len(tgs) == 1
    return tgs[0][1]


def _response_code_assertions(container):
    """ResponseAssertion elements that check the response CODE for 2xx/3xx (not the variable-scoped
    correlation-health assertions)."""
    out = []
    _collect(container, "ResponseAssertion", out)
    hits = []
    for a, ht in out:
        xml = a.toxml()
        if "Assertion.response_code" in xml and "Assert Response Code" in a.getAttribute("testname"):
            hits.append((a, ht))
    return hits


def _plan():
    res = analyze(_mixed_capture_har())
    xml = build_jmx_xml(res, {"threads": "10", "loops": "2", "ramp": "5", "thinktime": "700"})
    doc = minidom.parseString(xml)
    return res, doc, xml.decode("utf-8")


# ============================================================ Defect 1 — noise filtering

def test_third_party_iframe_and_xhr_noise_excluded_but_auth_dependency_kept():
    res, doc, xml = _plan()
    kept_hosts = {r.request.host for r in res.capture.requests if not r.classification.excluded}
    excluded_hosts = {r.request.host for r in res.capture.requests if r.classification.excluded}

    # (A) irrelevant third-party / browser traffic is excluded — including document/iframe-shaped maps
    #     and reCAPTCHA, which previously leaked through the navigation branch
    for noise in ("maps.googleapis.com", "www.google.com", "www.google-analytics.com", "fonts.gstatic.com"):
        assert noise in excluded_hosts, f"{noise} should be excluded"
        assert noise not in kept_hosts, f"{noise} should not be kept"

    # (B) a required EXTERNAL dependency (the identity provider) is preserved
    assert "auth.identity-provider.com" in kept_hosts

    # and none of the noise hosts reach the emitted plan as samplers
    for noise in ("maps.googleapis.com", "recaptcha", "google-analytics", "fonts.gstatic.com", "/maps/"):
        assert noise not in xml, f"{noise} leaked into the JMX"
    assert "auth.identity-provider.com" in xml or "/oauth/token" in xml   # dependency present


def test_exclusion_reasons_are_explainable():
    res = analyze(_mixed_capture_har())
    by_host = {r.request.host: r for r in res.capture.requests}
    # every exclusion carries a human-readable reason (not just a silent drop)
    for host in ("maps.googleapis.com", "www.google.com", "fonts.gstatic.com"):
        r = by_host[host]
        assert r.classification.excluded and r.classification.exclusion_reason
        assert "third-party" in r.classification.exclusion_reason or "telemetry" in r.classification.exclusion_reason


# ============================================================ Defect 2 — assertion placement

def test_one_response_assertion_per_transaction_on_anchor_sampler():
    _res, doc, _xml = _plan()
    tg = _thread_group_container(doc)

    # (E) NO response-code assertion directly at Thread Group level
    tg_direct = [a for a, _ in _response_code_assertions_direct(tg)]
    assert tg_direct == [], "a response-code assertion must not sit directly under the Thread Group"

    # exactly one response-code assertion per transaction (D), nested under a sampler — never a direct
    # child of the Transaction Controller, never one per sampler
    tcs = []
    _collect(tg, "TransactionController", tcs)
    assert len(tcs) >= 2
    for tc, tc_ht in tcs:
        deep = _response_code_assertions(tc_ht)               # anywhere in the transaction subtree
        assert len(deep) == 1, f"{tc.getAttribute('testname')} must have exactly one response assertion"
        assert _response_code_assertions_direct(tc_ht) == [], \
            f"{tc.getAttribute('testname')} assertion must be under a sampler, not a direct TC child"

    # and the plan-wide count equals the number of transactions (not one-per-sampler)
    total = _response_code_assertions(tg)
    assert len(total) == len(tcs)


def _response_code_assertions_direct(container):
    """Response-code assertions that are DIRECT children of `container` (not nested deeper)."""
    kids = _elems(container)
    out, i = [], 0
    while i < len(kids):
        e = kids[i]
        ht = kids[i + 1] if i + 1 < len(kids) and kids[i + 1].tagName == "hashTree" else None
        if e.tagName == "ResponseAssertion" and "Assertion.response_code" in e.toxml() \
                and "Assert Response Code" in e.getAttribute("testname"):
            out.append((e, ht))
        i += 2 if ht is not None else 1
    return out


# ============================================================ Defect 3 — think-time placement

def test_think_time_only_between_transactions():
    _res, doc, _xml = _plan()
    tg = _thread_group_container(doc)

    tcs = []
    _collect(tg, "TransactionController", tcs)
    n = len(tcs)
    assert n >= 2

    # (F) think time is emitted strictly BETWEEN transactions: N-1 pauses for N transactions
    think = []
    _collect(tg, "TestAction", think)
    assert len(think) == n - 1, f"expected {n-1} between-transaction pauses, got {len(think)}"

    # (G) no think time nests INSIDE a transaction controller (never between a transaction's requests)
    for _tc, tc_ht in tcs:
        inner = []
        _collect(tc_ht, "TestAction", inner)
        assert inner == [], "think time must not appear inside a transaction"

    # each Test Action carries its own scoped timer (so it can't pace the samplers)
    for ta, ta_ht in think:
        timers = _elems_by_tag(ta_ht, "UniformRandomTimer")
        assert len(timers) == 1


def test_no_think_time_in_single_transaction_plan():
    # a one-transaction capture has nothing to pause between → zero think times, and that is still a
    # production-clean plan (the dry-run validator no longer demands a timer here).
    from har2jmx.emit import validate_plan
    entries = [
        _entry("POST", "https://app.example.com/api/orders", "application/json",
               body={"item": "x"}, resp_body='{"order_id":"9"}',
               ts="2024-01-01T10:00:00.000Z", page="p1"),
    ]
    har = json.dumps({"log": {"version": "1.2", "entries": entries}}).encode()
    res = analyze(har)
    xml = build_jmx_xml(res, {"threads": "10"}).decode()
    assert 'testname="Think Time"' not in xml
    assert validate_plan(res, xml) == []


def _elems_by_tag(container, tag):
    out = []
    _collect(container, tag, out)
    return [e for e, _ in out]
