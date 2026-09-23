"""ISSUE 2 — business/login inputs (username/signInName/email/password and aliases) must be
parameterized (values in the CSV, ${var} in the request) even when the value is short, across JSON /
form-urlencoded / query, with URL encoding preserved. Server-generated values must still CORRELATE.
"""
from __future__ import annotations

import json
import re

from har2jmx.classify import ValueClass
from har2jmx.emit import build_jmx_xml, emit_jmx
from har2jmx.engine import analyze

_UDV = {"THREADS", "LOOPS", "RAMP", "THINKTIME", "BASE_URL", "PROTOCOL", "HOLD", "DURATION", "TIMEOUT"}


def _login(*, raw=None, body=None, ctype="application/json", url="https://app.example.com/api/login",
           method="POST", query=None, resp='{"access_token":"TKN-1"}'):
    ent = {"startedDateTime": "2024-01-01T10:00:00.000Z", "time": 30,
           "request": {"method": method, "url": url, "cookies": [], "queryString": query or [],
                       "headers": [{"name": "Content-Type", "value": ctype}]},
           "response": {"status": 200, "headers": [{"name": "Content-Type", "value": "application/json"}],
                        "content": {"mimeType": "application/json", "text": resp}}}
    if raw is not None:
        ent["request"]["postData"] = {"mimeType": ctype, "text": raw}
    elif body is not None:
        ent["request"]["postData"] = {"mimeType": ctype, "text": json.dumps(body)}
    return ent


def _plan(entries):
    res = analyze(json.dumps({"log": {"version": "1.2", "entries": entries}}).encode())
    return res, build_jmx_xml(res, {"threads": "5"}).decode()


def _cols(xml):
    out = []
    for names in re.findall(r'variableNames">([^<]+)<', xml):
        out += [c.strip() for c in names.split(",") if c.strip()]
    return out


def _vars(xml):
    return set(re.findall(r"\$\{(\w+)\}", xml)) - _UDV


def _assert_pair(entries, u_field, p_field):
    res, xml = _plan(entries)
    cols = _cols(xml)
    assert u_field in cols, f"{u_field} not parameterized (cols={cols})"
    assert p_field in cols, f"{p_field} not parameterized (cols={cols})"
    assert u_field in _vars(xml) and p_field in _vars(xml)
    return res, xml


def test_signInName_and_password_form():
    _assert_pair([_login(ctype="application/x-www-form-urlencoded",
                         raw="signInName=perfsuperuser%40mailinator.com&password=Aug%402026")],
                 "signInName", "password")


def test_username_and_password_json():
    _assert_pair([_login(body={"username": "bob", "password": "Secret123"})], "username", "password")


def test_email_and_password_json():
    _assert_pair([_login(body={"email": "bob@x.com", "password": "Secret123"})], "email", "password")


def test_url_encoded_email_password_preserved_in_csv(tmp_path):
    res = analyze(json.dumps({"log": {"version": "1.2", "entries": [
        _login(ctype="application/x-www-form-urlencoded",
               raw="signInName=perfsuperuser%40mailinator.com&password=Aug%402026")]}}).encode())
    jmx_path, csv_paths, _ = emit_jmx(res, tmp_path, {"threads": "5"}, name="cred")
    csv_blob = "".join(p.read_text(encoding="utf-8") for p in csv_paths)
    # the CSV stores the DECODED value; JMeter re-encodes form args at replay (encoding preserved)
    assert "perfsuperuser@mailinator.com" in csv_blob
    assert "Aug@2026" in csv_blob
    # and the request references the variables, not the literals
    xml = jmx_path.read_bytes().decode()
    assert "${signInName}" in xml and "${password}" in xml
    assert "perfsuperuser%40mailinator.com" not in xml and "Aug%402026" not in xml


def test_form_urlencoded_login_aliases():
    _assert_pair([_login(ctype="application/x-www-form-urlencoded", raw="userName=joe&passwd=Secret123")],
                 "userName", "passwd")


def test_query_credentials():
    _assert_pair([_login(method="GET", url="https://app.example.com/api/login?username=bob&password=Secret123",
                         query=[{"name": "username", "value": "bob"}, {"name": "password", "value": "Secret123"}])],
                 "username", "password")


def test_short_username_value_is_parameterized():
    # the real-world defect: a short username value ("bob", 3 chars) must still parameterize
    res, xml = _assert_pair([_login(body={"username": "bob", "password": "hunter2xx"})], "username", "password")
    v = next(v for v in res.classification.verdicts if v.value == "bob")
    assert v.classification == ValueClass.BUSINESS_MASTER_DATA          # BUSINESS_INPUT -> PARAMETERIZE


def test_business_value_reused_across_requests_is_one_parameter():
    res, xml = _plan([
        _login(body={"signInName": "perfuser@x.com", "password": "Secret123"}),
        {"startedDateTime": "2024-01-01T10:00:05.000Z", "time": 30,
         "request": {"method": "POST", "url": "https://app.example.com/api/profile", "cookies": [], "queryString": [],
                     "headers": [{"name": "Content-Type", "value": "application/json"}],
                     "postData": {"mimeType": "application/json", "text": json.dumps({"signInName": "perfuser@x.com"})}},
         "response": {"status": 200, "headers": [{"name": "Content-Type", "value": "application/json"}],
                      "content": {"mimeType": "application/json", "text": "{}"}}},
    ])
    assert _cols(xml).count("signInName") == 1                          # one logical parameter, reused


def test_server_generated_value_stays_correlated_not_parameterized():
    entries = [
        {"startedDateTime": "2024-01-01T10:00:00.000Z", "time": 30,
         "request": {"method": "POST", "url": "https://app.example.com/api/session", "cookies": [], "queryString": [],
                     "headers": [{"name": "Content-Type", "value": "application/json"}],
                     "postData": {"mimeType": "application/json", "text": "{}"}},
         "response": {"status": 200, "headers": [{"name": "Content-Type", "value": "application/json"}],
                      "content": {"mimeType": "application/json", "text": '{"userId":"USR-9f8e7d6c"}'}}},
        {"startedDateTime": "2024-01-01T10:00:01.000Z", "time": 30,
         "request": {"method": "GET", "url": "https://app.example.com/api/users/USR-9f8e7d6c", "cookies": [],
                     "queryString": [], "headers": []},
         "response": {"status": 200, "headers": [], "content": {"mimeType": "application/json", "text": "{}"}}},
    ]
    res, xml = _plan(entries)
    assert "userId" not in _cols(xml)                                   # NOT parameterized (would be wrong)
    extractors = set(re.findall(r'referenceNames">([^<]+)<', xml))
    assert "userId" in extractors                                      # correlated instead
