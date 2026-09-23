"""Validate the two defects at EVERY layer, not only final JMX:

  UI-model layer  — an excluded noise request appears ONLY in the web summary's ``excluded``
                    ("Noise filtered") audit list, never in transactions/correlations/parameters.
  JMX layer       — one response-code assertion per Transaction Controller, zero at Thread Group,
                    think time strictly between transactions and scoped to a Test Action.
  CSV layer       — every column is a genuine business/user input (no RUNTIME/STATIC values).

Uses the REAL repo fixture tests/fixtures/sample_noise.har (contains google-analytics telemetry) plus a
clearly-synthetic maps.googleapis.com case (no real maps HAR ships in the repo).
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from xml.dom import minidom

from har2jmx.classify import ValueClass
from har2jmx.emit import build_jmx_xml
from har2jmx.engine import analyze
from har2jmx.webreport import build_web_summary

FIX = Path(__file__).parent / "fixtures"


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
           "request": {"method": method, "url": url, "httpVersion": "HTTP/1.1",
                       "headers": H, "queryString": [], "cookies": []},
           "response": {"status": status, "headers": rh, "cookies": [],
                        "content": {"mimeType": rmime, "text": resp}}}
    if raw is not None:
        ent["request"]["postData"] = {"mimeType": ctype, "text": raw}
    elif body is not None:
        ent["request"]["postData"] = {"mimeType": ctype, "text": json.dumps(body)}
    return ent


def _analyze(entries):
    return analyze(json.dumps({"log": {"version": "1.2", "entries": entries}}).encode())


def _summary(res):
    return build_web_summary(res, "rid", {"jmx": "x", "zip": "x", "csvs": [], "reports": []})


def _multi_txn():
    return _analyze([
        _e("POST", "https://app.example.com/api/login", ctype="application/x-www-form-urlencoded",
           raw="signInName=perfSuperuser%40mailinator.com&password=Aug%402026",
           set_cookie="JSESSIONID=sess-abc-123; Path=/", resp='{"access_token":"TKN-987"}', sec=0, page="p1"),
        _e("GET", "https://maps.googleapis.com/maps/api/js?key=K", rmime="text/javascript", sec=6, page="p2"),
        _e("GET", "https://www.google-analytics.com/g/collect?v=2", rmime="image/gif", sec=6, page="p2"),
        _e("GET", "https://app.example.com/assets/app.css", rmime="text/css", sec=6, page="p2"),
        _e("GET", "https://app.example.com/api/customers?q=acme&apiVersion=v2", hdr={"Authorization": "Bearer TKN-987"},
           resp='{"customers":[{"customerId":"CUST-9","name":"Acme"}]}', sec=6, page="p2"),
        _e("POST", "https://app.example.com/api/orders", hdr={"Authorization": "Bearer TKN-987"}, body={"item": "widget"},
           resp='{"orderId":"ORD-77"}', sec=12, page="p3"),
        _e("GET", "https://app.example.com/api/orders/ORD-77", hdr={"Authorization": "Bearer TKN-987"},
           resp='{"orderId":"ORD-77"}', sec=14, page="p3"),
    ])


# ---- JMX structural helpers -------------------------------------------------

def _elems(n):
    return [c for c in n.childNodes if c.nodeType == c.ELEMENT_NODE]


def _rc_assertions(container):
    k = _elems(container)
    out, i = [], 0
    while i < len(k):
        el = k[i]
        ht = k[i + 1] if i + 1 < len(k) and k[i + 1].tagName == "hashTree" else None
        if el.tagName == "ResponseAssertion" and "Assertion.response_code" in el.toxml():
            out.append(el)
        i += 2 if ht is not None else 1
    return out


def _thread_group(doc):
    box = [None]

    def find(c):
        k = _elems(c)
        i = 0
        while i < len(k):
            el = k[i]
            ht = k[i + 1] if i + 1 < len(k) and k[i + 1].tagName == "hashTree" else None
            if el.tagName == "ThreadGroup" and ht is not None:
                box[0] = ht
                return
            if el.tagName == "hashTree":
                find(el)
            elif ht is not None:
                find(ht)
            i += 2 if ht is not None else 1
    find(doc.documentElement)
    return box[0]


# ============================ UI-MODEL LAYER ============================

def test_synthetic_maps_only_in_excluded_not_in_model():
    res = _multi_txn()
    p = _summary(res)
    labels = " ".join(x["label"] + " " + x["reason"] for x in p["excluded"])
    assert "/maps/" in labels                                  # maps IS shown in the Noise-filtered panel
    assert any(x["role"] == "telemetry" and "maps" in x["reason"] for x in p["excluded"])
    # ... and NOT in the performance model
    assert not any("maps" in str(t).lower() for t in p["transactions"])
    assert not any("maps" in str(c).lower() for c in p["correlations"])
    assert not any("maps" in str(pp).lower() for pp in p["parameters"])
    assert "maps.googleapis.com" not in build_jmx_xml(res).decode()


def test_real_noise_fixture_analytics_excluded_in_ui():
    # REAL repo fixture: sample_noise.har carries a google-analytics beacon
    res = analyze((FIX / "sample_noise.har").read_bytes())
    p = _summary(res)
    ga = [x for x in p["excluded"] if "collect" in x["label"] or "analytic" in x["reason"].lower()]
    assert ga and ga[0]["reason"]                              # excluded WITH a reason
    xml = build_jmx_xml(res).decode()
    assert "google-analytics" not in xml
    assert not any("google-analytics" in str(t).lower() for t in p["transactions"])


def test_every_excluded_request_has_a_reason():
    res = _multi_txn()
    for x in _summary(res)["excluded"]:
        assert x["reason"], f"excluded request {x['label']} has no reason"


# ============================ JMX LAYER ============================

def test_one_assertion_per_transaction_zero_at_thread_group():
    res = _multi_txn()
    doc = minidom.parseString(build_jmx_xml(res).decode())
    tg = _thread_group(doc)
    assert len(_rc_assertions(tg)) == 0                        # zero at Thread Group
    k = _elems(tg)
    i, tcs = 0, 0
    while i < len(k):
        el = k[i]
        ht = k[i + 1] if i + 1 < len(k) and k[i + 1].tagName == "hashTree" else None
        if el.tagName == "TransactionController" and ht is not None:
            tcs += 1
            assert len(_rc_assertions(ht)) == 1               # exactly one per TC
        i += 2 if ht is not None else 1
    assert tcs >= 2
    # no per-sampler duplication: total assertions == transaction count
    assert build_jmx_xml(res).decode().count('testname="Assert Response Code (2xx/3xx)"') == tcs


def test_think_time_between_transactions_and_scoped():
    res = _multi_txn()
    xml = build_jmx_xml(res, {"threads": "5", "thinktime": "800"}).decode()
    doc = minidom.parseString(xml)
    tg = _thread_group(doc)
    k = _elems(tg)
    i, tcs, tt = 0, 0, 0
    bare_timer = False
    while i < len(k):
        el = k[i]
        ht = k[i + 1] if i + 1 < len(k) and k[i + 1].tagName == "hashTree" else None
        if el.tagName == "TransactionController":
            tcs += 1
        elif el.tagName == "TestAction" and "Think Time" in el.getAttribute("testname"):
            tt += 1
        elif el.tagName in ("ConstantTimer", "UniformRandomTimer"):
            bare_timer = True                                 # a timer directly at Thread Group scope
        i += 2 if ht is not None else 1
    assert tt == tcs - 1                                       # strictly between transactions
    assert not bare_timer                                      # never applies to the whole Thread Group
    assert re.search(r'testclass="TestAction".*?<hashTree>\s*<UniformRandomTimer', xml, re.S)  # scoped


# ============================ CSV LAYER ============================

def test_csv_columns_are_business_inputs_only():
    res = _multi_txn()
    xml = build_jmx_xml(res).decode()
    cols = []
    for names in re.findall(r'variableNames">([^<]+)<', xml):
        cols += [c.strip() for c in names.split(",") if c.strip()]
    by_val = {v.value: v for v in res.classification.verdicts}
    for d in res.parameterization.datasets:
        for c in d.columns:
            sample = str(d.rows[0].get(c.name, "")) if d.rows else ""
            verd = by_val.get(sample)
            # every CSV value is business/master data (user input) — never a runtime/static value
            assert verd is None or verd.classification == ValueClass.BUSINESS_MASTER_DATA, \
                f"CSV column {c.name} carries a {verd.classification} value"
            assert ("${%s}" % c.name) in xml                  # and it is actually referenced
    # runtime ids are correlated, not CSV
    assert "orderId" not in cols and "access_token" not in cols and "JSESSIONID" not in cols
