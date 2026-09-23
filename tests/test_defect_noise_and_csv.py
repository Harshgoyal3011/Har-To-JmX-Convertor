"""Regression coverage for two defects, verified against the ACTUAL generated JMX + CSV:

  Defect 1 — irrelevant browser/third-party/telemetry/static traffic must not reach the JMX, while
             required external dependencies (auth, backend) are retained.
  Defect 2 — the CSV must contain only meaningful, actually-referenced business test data: no static
             values, no server-generated (correlation-only) values, no unused or duplicate columns.

The cases map 1:1 to the 13 mandated regression cases.
"""
from __future__ import annotations

import json
import re

from har2jmx.emit import build_jmx_xml
from har2jmx.engine import analyze

_UDV = {"THREADS", "LOOPS", "RAMP", "THINKTIME", "BASE_URL", "PROTOCOL", "HOLD", "DURATION", "TIMEOUT"}


def _e(method, url, *, hdr=None, body=None, raw=None, ctype="application/json", resp="{}",
       rmime="application/json", set_cookie=None, status=200, ts="2024-01-01T10:00:00.000Z", page="p1"):
    H = [{"name": "Content-Type", "value": ctype}, {"name": "Accept", "value": "application/json"},
         {"name": "User-Agent", "value": "Mozilla/5.0"}]
    for k, v in (hdr or {}).items():
        H.append({"name": k, "value": v})
    rh = [{"name": "Content-Type", "value": rmime}]
    if set_cookie:
        rh.append({"name": "Set-Cookie", "value": set_cookie})
    ent = {"pageref": page, "startedDateTime": ts, "time": 80,
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


def _vars(xml):
    return set(re.findall(r"\$\{(\w+)\}", xml)) - _UDV


def _csv_cols(xml):
    cols = []
    for names in re.findall(r'variableNames">([^<]+)<', xml):
        cols += [c.strip() for c in names.split(",") if c.strip()]
    return cols


def _kept_hosts(res):
    return {r.request.host for r in res.capture.requests if not r.classification.excluded}


def _excluded_hosts(res):
    return {r.request.host for r in res.capture.requests if r.classification.excluded}


# ---- one shared capture exercising the whole workload -------------------------------------------

def _mixed():
    return _analyze([
        _e("POST", "https://auth.identity-provider.com/oauth/token", ctype="application/x-www-form-urlencoded",
           raw="signInName=perfSuperuser%40mailinator.com&password=Aug%402026",
           set_cookie="JSESSIONID=sess-abc-xyz-123; Path=/",
           resp='{"access_token":"TKN-987","orderId":"ORD-55"}', ts="2024-01-01T10:00:00.000Z", page="p1"),
        _e("GET", "https://www.google-analytics.com/g/collect?v=2", rmime="image/gif",
           ts="2024-01-01T10:00:00.300Z", page="p1"),
        _e("GET", "https://maps.googleapis.com/maps/api/js?key=K", rmime="text/javascript",
           ts="2024-01-01T10:00:10.000Z", page="p2"),
        _e("GET", "https://maps.googleapis.com/maps/api/geocode/json?address=NYC", resp='{"r":[]}',
           ts="2024-01-01T10:00:10.100Z", page="p2"),
        _e("GET", "https://unknown-widget-cdn.io/embed/widget.js", rmime="application/javascript",
           ts="2024-01-01T10:00:10.200Z", page="p2"),
        _e("GET", "https://app.example.com/assets/main.css", rmime="text/css",
           ts="2024-01-01T10:00:10.300Z", page="p2"),
        _e("GET", "https://app.example.com/api/customers?q=acme&apiVersion=v2&sortOrder=asc&pageSize=20&active=true",
           hdr={"Authorization": "Bearer TKN-987"},
           resp='{"customers":[{"customerId":"CUST-9","name":"Acme"}]}', ts="2024-01-01T10:00:12.000Z", page="p2"),
        _e("GET", "https://api.partner-backend.com/v1/inventory?sku=SKU-1", hdr={"Authorization": "Bearer TKN-987"},
           resp='{"stock":5}', ts="2024-01-01T10:00:12.300Z", page="p2"),
        _e("POST", "https://app.example.com/api/orders", hdr={"Authorization": "Bearer TKN-987"},
           body={"item": "widget", "express": True, "quantity": 1}, resp='{"orderId":"ORD-77"}', status=201,
           ts="2024-01-01T10:00:12.600Z", page="p2"),
        _e("GET", "https://app.example.com/api/orders/ORD-77", hdr={"Authorization": "Bearer TKN-987"},
           resp='{"orderId":"ORD-77","status":"ok"}', ts="2024-01-01T10:00:20.000Z", page="p3"),
        _e("POST", "https://app.example.com/api/profile", hdr={"Authorization": "Bearer TKN-987"},
           body={"signInName": "perfSuperuser@mailinator.com", "note": "hello there test note"},
           resp='{"ok":true}', ts="2024-01-01T10:00:31.000Z", page="p4"),
    ])


# ========================= Defect 1 — noise exclusion =========================

def test_case1_maps_googleapis_excluded_from_jmx():
    res = _mixed()
    xml = build_jmx_xml(res).decode()
    assert "maps.googleapis.com" not in xml and "/maps/" not in xml
    assert "maps.googleapis.com" in _excluded_hosts(res)


def test_case2_unknown_third_party_ui_script_excluded():
    res = _mixed()
    assert "unknown-widget-cdn.io" in _excluded_hosts(res)
    assert "unknown-widget-cdn" not in build_jmx_xml(res).decode()


def test_case3_required_external_auth_service_retained():
    res = _mixed()
    assert "auth.identity-provider.com" in _kept_hosts(res)
    assert "/oauth/token" in build_jmx_xml(res).decode()


def test_case4_required_external_backend_dependency_retained():
    res = _mixed()
    assert "api.partner-backend.com" in _kept_hosts(res)
    assert "/v1/inventory" in build_jmx_xml(res).decode()


def test_case5_static_resource_excluded():
    res = _mixed()
    assert "app.example.com" in _kept_hosts(res)          # the app itself stays
    # but its static asset is excluded and never a sampler
    assert not any(r.request.path.endswith("main.css") and not r.classification.excluded
                   for r in res.capture.requests)
    assert "main.css" not in build_jmx_xml(res).decode()


def test_case6_telemetry_analytics_excluded():
    res = _mixed()
    assert "www.google-analytics.com" in _excluded_hosts(res)
    assert "google-analytics" not in build_jmx_xml(res).decode()


def test_case7_real_business_api_retained():
    res = _mixed()
    xml = build_jmx_xml(res).decode()
    assert "/api/customers" in xml and "/api/orders" in xml


# ========================= Defect 2 — CSV minimization =========================

def test_case8_signInName_parameterized():
    res = _mixed()
    assert "signInName" in _vars(build_jmx_xml(res).decode())


def test_case9_password_parameterized_via_testdata():
    res = _mixed()
    xml = build_jmx_xml(res).decode()
    assert "password" in _vars(xml) and "password" in _csv_cols(xml)
    assert "Aug@2026" not in xml and "Aug%402026" not in xml     # secret not embedded literally


def test_case10_static_config_values_not_parameterized():
    res = _mixed()
    cols = {c.lower() for c in _csv_cols(build_jmx_xml(res).decode())}
    for static in ("apiversion", "sortorder", "pagesize", "active", "express", "quantity",
                   "contenttype", "accept", "useragent"):
        assert static not in cols


def test_case11_server_generated_id_correlated_not_csv():
    res = _mixed()
    xml = build_jmx_xml(res).decode()
    cols = {c.lower() for c in _csv_cols(xml)}
    for runtime in ("orderid", "access_token", "accesstoken", "jsessionid", "customerid"):
        assert runtime not in cols
    assert "/api/orders/${orderId}" in xml                        # correlated into the path


def test_case12_unreferenced_candidate_has_no_csv_column():
    res = _mixed()
    xml = build_jmx_xml(res).decode()
    assert set(_csv_cols(xml)) <= _vars(xml)                      # every column is referenced


def test_case13_duplicate_business_value_is_one_column():
    res = _mixed()
    cols = _csv_cols(build_jmx_xml(res).decode())
    assert cols.count("signInName") == 1                          # login + profile share one column


def test_no_duplicate_csv_variable_names():
    res = _mixed()
    cols = _csv_cols(build_jmx_xml(res).decode())
    assert len(cols) == len(set(cols))
