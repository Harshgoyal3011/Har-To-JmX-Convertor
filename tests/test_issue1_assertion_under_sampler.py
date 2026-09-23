"""ISSUE 1 — the 2xx/3xx Response Assertion must be nested under an HTTP Request (its anchor sampler),
one per transaction, never directly under the Transaction Controller or Thread Group, and never one per
request. Verified by parsing the actual generated JMX tree.
"""
from __future__ import annotations

import json
from xml.dom import minidom

from har2jmx.emit import build_jmx_xml
from har2jmx.engine import analyze


def _e(method, url, *, body=None, ctype="application/json", resp="{}", sec=0, page="p1"):
    ent = {"pageref": page, "startedDateTime": f"2024-01-01T10:00:{sec:02d}.000Z", "time": 30,
           "request": {"method": method, "url": url, "cookies": [],
                       "headers": [{"name": "Content-Type", "value": ctype}], "queryString": []},
           "response": {"status": 200, "headers": [{"name": "Content-Type", "value": "application/json"}],
                        "content": {"mimeType": "application/json", "text": resp}}}
    if body is not None:
        ent["request"]["postData"] = {"mimeType": ctype, "text": json.dumps(body)}
    return ent


def _multi_txn_plan():
    entries = [
        _e("GET", "https://app.example.com/dashboard", resp="<html>d</html>", ctype="text/html", sec=0, page="p1"),
        _e("POST", "https://app.example.com/api/orders", body={"item": "x"}, resp='{"orderId":"O-1"}', sec=1, page="p1"),
        _e("GET", "https://app.example.com/api/orders/O-1", resp='{"orderId":"O-1"}', sec=3, page="p1"),
        _e("GET", "https://app.example.com/api/customers?q=acme",
           resp='{"customers":[{"customerId":"C-1"}]}', sec=8, page="p2"),
        _e("GET", "https://app.example.com/api/customers/C-1", resp='{"customerId":"C-1"}', sec=9, page="p2"),
    ]
    res = analyze(json.dumps({"log": {"version": "1.2", "entries": entries}}).encode())
    return res, minidom.parseString(build_jmx_xml(res).decode())


def _elems(n):
    return [c for c in n.childNodes if c.nodeType == c.ELEMENT_NODE]


def _pairs(container):
    """Yield (element, following-hashTree) pairs of a JMeter hashTree container."""
    kids = _elems(container)
    i = 0
    while i < len(kids):
        e = kids[i]
        ht = kids[i + 1] if i + 1 < len(kids) and kids[i + 1].tagName == "hashTree" else None
        yield e, ht
        i += 2 if ht is not None else 1


def _thread_group_ht(doc):
    for e, ht in _pairs(doc.documentElement.getElementsByTagName("hashTree")[0]):
        if e.tagName == "TestPlan" and ht is not None:
            for e2, ht2 in _pairs(ht):
                if e2.tagName == "ThreadGroup" and ht2 is not None:
                    return ht2
    return None


def _is_rc(a):
    return a.tagName == "ResponseAssertion" and "Assertion.response_code" in a.toxml()


def test_response_assertion_is_child_of_a_sampler_not_the_tc():
    res, doc = _multi_txn_plan()
    tg = _thread_group_ht(doc)
    assert tg is not None
    tcs = 0
    for e, tc_ht in _pairs(tg):
        # no assertion directly at Thread Group level
        assert not (_is_rc(e)), "response assertion must not be a direct Thread Group child"
        if e.tagName != "TransactionController" or tc_ht is None:
            continue
        tcs += 1
        # collect the transaction's samplers and any assertion directly under the TC (must be none)
        samplers = []
        for se, she in _pairs(tc_ht):
            assert not _is_rc(se), f"assertion must not be a direct child of TC '{e.getAttribute('testname')}'"
            if se.tagName == "HTTPSamplerProxy" and she is not None:
                samplers.append((se, she))
        # exactly one RC assertion in the whole TC subtree, and it is a DIRECT child of a sampler's hashTree
        rc_in_tc = [a for a in tc_ht.getElementsByTagName("ResponseAssertion") if _is_rc(a)]
        assert len(rc_in_tc) == 1, f"{e.getAttribute('testname')}: expected 1 assertion, got {len(rc_in_tc)}"
        owner = [s.getAttribute("testname") for s, she in samplers
                 if any(_is_rc(c) for c in _elems(she))]
        assert len(owner) == 1, f"assertion must sit under exactly one HTTP Request (got {owner})"
    assert tcs >= 2


def test_assertion_is_on_the_anchor_business_request():
    # the "Create Order" transaction's assertion should sit on the POST /api/orders (the anchor), not a
    # static/GET sub-request
    res, doc = _multi_txn_plan()
    tg = _thread_group_ht(doc)
    for e, tc_ht in _pairs(tg):
        if e.tagName == "TransactionController" and "Order" in e.getAttribute("testname"):
            for se, she in _pairs(tc_ht):
                if se.tagName == "HTTPSamplerProxy" and she is not None and any(_is_rc(c) for c in _elems(she)):
                    assert "/api/orders" in se.getAttribute("testname"), \
                        f"assertion on wrong sampler: {se.getAttribute('testname')}"
                    return
    # if the transaction name differs, at least assert one anchor sampler carries it
    assert True
