"""Correlation MATERIALIZATION: the emitted JMX is the source of truth.

A correlation is successful only when the final plan proves it — extractor on the producer sampler,
${var} referenced by the consumer, and the original value gone in EVERY representation. Each test here
asserts BOTH halves: (A) the correlation object reports success, and (B) the generated JMX actually
contains ${variable}. (A) alone is never sufficient — that is exactly the defect these tests guard.
"""
from __future__ import annotations

import json
import re

from har2jmx.emit import build_jmx_xml, validate_plan
from har2jmx.engine import analyze
from har2jmx.validate import MaterializationStatus, audit_materialization

TOKEN = "REF 12345"          # contains a SPACE -> consumers may send it percent-encoded
OPAQUE = "TKNa1b2c3d4e5f6"


def _post(url, resp, *, sec=0, body=None, status=201):
    return {"startedDateTime": f"2024-01-01T10:00:{sec:02d}.000Z", "time": 30,
            "request": {"method": "POST", "url": url, "cookies": [], "queryString": [],
                        "headers": [{"name": "Content-Type", "value": "application/json"}],
                        "postData": {"mimeType": "application/json",
                                     "text": json.dumps(body or {"n": "a"})}},
            "response": {"status": status,
                         "headers": [{"name": "Content-Type", "value": "application/json"}],
                         "cookies": [], "content": {"mimeType": "application/json", "text": resp}}}


def _get(url, *, sec=1, hdr=None):
    return {"startedDateTime": f"2024-01-01T10:00:{sec:02d}.000Z", "time": 30,
            "request": {"method": "GET", "url": url, "cookies": [], "queryString": [],
                        "headers": hdr or []},
            "response": {"status": 200, "headers": [], "cookies": [],
                         "content": {"mimeType": "application/json", "text": "{}"}}}


def _body(url, payload, *, sec=1):
    return {"startedDateTime": f"2024-01-01T10:00:{sec:02d}.000Z", "time": 30,
            "request": {"method": "POST", "url": url, "cookies": [], "queryString": [],
                        "headers": [{"name": "Content-Type", "value": "application/json"}],
                        "postData": {"mimeType": "application/json", "text": json.dumps(payload)}},
            "response": {"status": 200, "headers": [], "cookies": [],
                         "content": {"mimeType": "application/json", "text": "{}"}}}


def _run(entries):
    res = analyze(json.dumps({"log": {"version": "1.2", "entries": entries}}).encode())
    return res, build_jmx_xml(res).decode()


def _assert_materialized(res, xml, value):
    """(A) the correlation is reported successful AND (B) the JMX proves it."""
    dec = [c for c in res.correlations if str(c.value) == value]
    assert dec, f"{value!r} was not correlated at all"
    d = dec[0]

    # (A) the audit — run against the FINAL plan — says materialized
    checks = [c for c in audit_materialization(res, xml) if c.variable == d.variable]
    assert checks, f"no materialization check produced for {d.variable}"
    assert checks[0].status == MaterializationStatus.MATERIALIZED, checks[0].diagnostic()

    # (B) independently: the variable really is in the XML and no representation of the literal remains
    assert ("${%s}" % d.variable) in xml, f"${{{d.variable}}} missing from the generated JMX"
    from urllib.parse import quote, quote_plus
    for rep in {value, quote(value, safe=""), quote_plus(value), quote(value, safe="/")}:
        assert rep not in xml, f"consumer still sends the literal representation {rep!r}"
    assert validate_plan(res, xml) == []
    return d


# ---------------------------------------------------------------- the ten required cases

def test_1_exact_literal_substitution():
    res, xml = _run([_post("https://x.io/api/create", json.dumps({"ref": OPAQUE})),
                     _get(f"https://x.io/api/use/{OPAQUE}")])
    _assert_materialized(res, xml, OPAQUE)


def test_2_url_encoded_consumer_value():
    # producer returns "REF 12345"; the consumer sends it percent-encoded
    res, xml = _run([_post("https://x.io/api/create", json.dumps({"ref": TOKEN})),
                     _get("https://x.io/api/use/REF%2012345")])
    _assert_materialized(res, xml, TOKEN)


def test_3_query_parameter_substitution():
    res, xml = _run([_post("https://x.io/api/create", json.dumps({"ref": OPAQUE})),
                     _get(f"https://x.io/api/lookup?handle={OPAQUE}")])
    d = _assert_materialized(res, xml, OPAQUE)
    assert re.search(r'Argument\.value">\$\{%s\}<' % d.variable, xml), "query arg not substituted"


def test_4_path_substitution():
    res, xml = _run([_post("https://x.io/api/create", json.dumps({"ref": OPAQUE})),
                     _get(f"https://x.io/api/items/{OPAQUE}/detail")])
    d = _assert_materialized(res, xml, OPAQUE)
    paths = re.findall(r'HTTPSampler\.path">([^<]*)<', xml)
    assert any(("${%s}" % d.variable) in p for p in paths), f"path not substituted: {paths}"


def test_5_encoded_path_substitution():
    res, xml = _run([_post("https://x.io/api/create", json.dumps({"ref": TOKEN})),
                     _get("https://x.io/api/items/REF%2012345/detail")])
    d = _assert_materialized(res, xml, TOKEN)
    paths = re.findall(r'HTTPSampler\.path">([^<]*)<', xml)
    assert any(p == "/api/items/${%s}/detail" % d.variable for p in paths), \
        f"encoded path segment not replaced by the variable: {paths}"


def test_6_json_body_substitution():
    res, xml = _run([_post("https://x.io/api/create", json.dumps({"ref": OPAQUE})),
                     _body("https://x.io/api/confirm", {"whateverName": OPAQUE})])
    _assert_materialized(res, xml, OPAQUE)


def test_7_header_substitution():
    res, xml = _run([_post("https://x.io/api/create", json.dumps({"ref": OPAQUE})),
                     _get("https://x.io/api/me", hdr=[{"name": "X-Session", "value": OPAQUE}])])
    _assert_materialized(res, xml, OPAQUE)


def test_8_value_appears_more_than_once_in_one_consumer():
    res, xml = _run([_post("https://x.io/api/create", json.dumps({"ref": OPAQUE})),
                     _get(f"https://x.io/api/items/{OPAQUE}/related?peer={OPAQUE}")])
    d = _assert_materialized(res, xml, OPAQUE)
    assert xml.count("${%s}" % d.variable) >= 2, "both occurrences should be substituted"


def test_9_same_value_used_by_multiple_consumers():
    res, xml = _run([_post("https://x.io/api/create", json.dumps({"ref": OPAQUE})),
                     _get(f"https://x.io/api/a/{OPAQUE}", sec=1),
                     _body("https://x.io/api/b", {"peer": OPAQUE}, sec=2)])
    d = _assert_materialized(res, xml, OPAQUE)
    assert len([c for c in res.correlations if str(c.value) == OPAQUE]) == 1, "one extractor only"
    assert len(d.consumers) >= 2


def test_10_producer_and_consumer_differ_only_by_encoding():
    # the ONLY difference between producer and consumer representation is the encoding
    res, xml = _run([_post("https://x.io/api/create", json.dumps({"ref": TOKEN})),
                     _get("https://x.io/api/lookup?handle=REF+12345")])
    _assert_materialized(res, xml, TOKEN)


# ---------------------------------------------------------------- the audit must be able to FAIL

def test_audit_detects_a_plan_where_the_variable_was_lost():
    """Guard against the audit rubber-stamping: put the literal back and it must report FAILED."""
    res, xml = _run([_post("https://x.io/api/create", json.dumps({"ref": OPAQUE})),
                     _get(f"https://x.io/api/use/{OPAQUE}")])
    d = [c for c in res.correlations if str(c.value) == OPAQUE][0]
    broken = xml.replace("${%s}" % d.variable, OPAQUE)          # simulate a lost substitution
    checks = [c for c in audit_materialization(res, broken) if c.variable == d.variable]
    assert checks and checks[0].status == MaterializationStatus.FAILED
    assert "MATERIALIZATION_FAILED" in checks[0].diagnostic()
    assert validate_plan(res, broken), "validate_plan must surface a non-materialized correlation"


def test_cookie_manager_correlation_is_not_a_materialization_failure():
    res, xml = _run([
        {"startedDateTime": "2024-01-01T10:00:00.000Z", "time": 30,
         "request": {"method": "POST", "url": "https://x.io/api/login", "cookies": [], "queryString": [],
                     "headers": [{"name": "Content-Type", "value": "application/json"}],
                     "postData": {"mimeType": "application/json", "text": "{}"}},
         "response": {"status": 200,
                      "headers": [{"name": "Set-Cookie", "value": "SID=sess-abc-98765; Path=/"}],
                      "cookies": [], "content": {"mimeType": "application/json", "text": "{}"}}},
        {"startedDateTime": "2024-01-01T10:00:02.000Z", "time": 30,
         "request": {"method": "GET", "url": "https://x.io/api/me", "queryString": [], "headers": [],
                     "cookies": [{"name": "SID", "value": "sess-abc-98765"}]},
         "response": {"status": 200, "headers": [], "cookies": [],
                      "content": {"mimeType": "application/json", "text": "{}"}}},
    ])
    assert all(c.status != MaterializationStatus.FAILED for c in audit_materialization(res, xml))
