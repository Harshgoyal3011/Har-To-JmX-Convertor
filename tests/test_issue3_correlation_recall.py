"""ISSUE 3 — correlation engine recall/correctness, domain-agnostic.

Every SERVER-CREATED dynamic value with a real downstream dependency must reach the JMX as
extractor -> ${var} -> consumer, regardless of field name / location / encoding, and each correlation
is VERIFIED (its extractor resolves to the recorded value) — not merely decided. Correlation is proven
name-independent (producer/consumer field names differ, and are unfamiliar). User-supplied business
inputs are NOT correlated, and no false correlation is emitted (a non-resolving extractor is dropped).
"""
from __future__ import annotations

import json

from har2jmx.emit import build_jmx_xml
from har2jmx.engine import analyze

JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abcDEF123ghiJKL456mnoPQR"
UUID = "550e8400-e29b-41d4-a716-446655440000"
B64 = "ZXlKaGJHY2lPaUpJVXpJMU5pSjkubm9wYXlsb2Fk"
OPAQUE = "a8F7kP2xQ91zR4mN"
HEX = "8f42a91b7e0c4d5a6b3f00"


def _post(url, resp, *, sec=0, body=None):
    return {"startedDateTime": f"2024-01-01T10:00:{sec:02d}.000Z", "time": 30,
            "request": {"method": "POST", "url": url, "cookies": [], "queryString": [],
                        "headers": [{"name": "Content-Type", "value": "application/json"}],
                        "postData": {"mimeType": "application/json", "text": json.dumps(body or {"n": "a"})}},
            "response": {"status": 201, "headers": [{"name": "Content-Type", "value": "application/json"}],
                         "cookies": [], "content": {"mimeType": "application/json", "text": resp}}}


def _get(url, *, sec=1, hdr=None):
    return {"startedDateTime": f"2024-01-01T10:00:{sec:02d}.000Z", "time": 30,
            "request": {"method": "GET", "url": url, "cookies": [], "queryString": [],
                        "headers": hdr or []},
            "response": {"status": 200, "headers": [], "cookies": [],
                         "content": {"mimeType": "application/json", "text": "{}"}}}


def _consume_body(url, body, *, sec=1):
    return {"startedDateTime": f"2024-01-01T10:00:{sec:02d}.000Z", "time": 30,
            "request": {"method": "POST", "url": url, "cookies": [], "queryString": [],
                        "headers": [{"name": "Content-Type", "value": "application/json"}],
                        "postData": {"mimeType": "application/json", "text": json.dumps(body)}},
            "response": {"status": 200, "headers": [], "cookies": [],
                         "content": {"mimeType": "application/json", "text": "{}"}}}


def _run(entries):
    res = analyze(json.dumps({"log": {"version": "1.2", "entries": entries}}).encode())
    return res, build_jmx_xml(res).decode()


def _assert_correlated(res, xml, value):
    """Full path: decision -> verified extractor -> variable -> consumer substitution -> literal gone."""
    ok_vals = {c.value for c in res.extractor_checks if c.ok}
    dec = [c for c in res.correlations if c.value == value]
    assert dec, f"{value!r} was not correlated"
    d = dec[0]
    assert d.consumers, f"{value!r} correlated without a downstream consumer"
    assert value in ok_vals, f"{value!r} extractor did not verify (would be NOT_FOUND at run time)"
    assert value not in xml, f"{value!r} literal still hardcoded in the JMX"
    assert ("${%s}" % d.variable) in xml, f"variable ${{{d.variable}}} not used downstream"


# ---- value shapes: JWT / Base64 / UUID / numeric / opaque / hex ------------------------------------

def test_jwt_created_then_reused_different_field_name():
    res, xml = _run([_post("https://x.io/api/auth", json.dumps({"abc": JWT})),
                     _consume_body("https://x.io/api/verify", {"verification": JWT})])
    _assert_correlated(res, xml, JWT)


def test_base64_token_correlated():
    res, xml = _run([_post("https://x.io/api/init", json.dumps({"blob": B64})),
                     _consume_body("https://x.io/api/step2", {"payloadRef": B64})])
    _assert_correlated(res, xml, B64)


def test_uuid_body_to_url_path():
    res, xml = _run([_post("https://x.io/api/resources", json.dumps({"xyz": UUID})),
                     _get(f"https://x.io/api/resources/{UUID}/detail")])
    _assert_correlated(res, xml, UUID)


def test_numeric_generated_id_correlated():
    res, xml = _run([_post("https://x.io/api/widgets", json.dumps({"newThing": "99881234"})),
                     _get("https://x.io/api/widgets/99881234")])
    _assert_correlated(res, xml, "99881234")


def test_hex_nested_object_id_diff_names():
    res, xml = _run([_post("https://x.io/api/orders", json.dumps({"data": {"inner": {"zzz": HEX}}})),
                     _consume_body("https://x.io/api/pay", {"orderKeyDiff": HEX})])
    _assert_correlated(res, xml, HEX)


# ---- location transforms: body -> query / header --------------------------------------------------

def test_body_to_query_param():
    res, xml = _run([_post("https://x.io/api/tickets", json.dumps({"handleThing": OPAQUE})),
                     _get(f"https://x.io/api/lookup?anyparam={OPAQUE}")])
    _assert_correlated(res, xml, OPAQUE)


def test_body_to_authorization_header():
    res, xml = _run([_post("https://x.io/api/login", json.dumps({"weirdName": JWT})),
                     _get("https://x.io/api/me", hdr=[{"name": "Authorization", "value": "Bearer " + JWT}])])
    _assert_correlated(res, xml, JWT)


# ---- encoding + collections -----------------------------------------------------------------------

def test_urlencoded_downstream_value():
    res, xml = _run([_post("https://x.io/api/make", json.dumps({"ref": "ABC/123+xy9z"})),
                     _get("https://x.io/api/g?p=ABC%2F123%2Bxy9z")])
    _assert_correlated(res, xml, "ABC/123+xy9z")


def test_array_member_value():
    res, xml = _run([_post("https://x.io/api/batch", json.dumps({"items": [{"q": UUID}]})),
                     _get(f"https://x.io/api/items/{UUID}")])
    _assert_correlated(res, xml, UUID)


# ---- embedded-in-prose (the newly-fixed miss) -----------------------------------------------------

def test_token_embedded_in_free_text_prose():
    res, xml = _run([_post("https://x.io/api/session", '{"msg":"your access token is ' + OPAQUE + ' thanks"}'),
                     _consume_body("https://x.io/api/use", {"whatever": OPAQUE})])
    _assert_correlated(res, xml, OPAQUE)


# ---- multiple consumers / multiple producers ------------------------------------------------------

def test_multiple_consumers_one_extractor():
    res, xml = _run([_post("https://x.io/api/create", json.dumps({"foo": OPAQUE})),
                     _get(f"https://x.io/api/a/{OPAQUE}", sec=1),
                     _consume_body("https://x.io/api/b", {"bar": OPAQUE}, sec=2)])
    _assert_correlated(res, xml, OPAQUE)
    decs = [c for c in res.correlations if c.value == OPAQUE]
    assert len(decs) == 1, "one logical dependency must yield exactly one extractor"
    assert len(decs[0].consumers) >= 2


def test_multiple_producers_pick_earliest():
    res, xml = _run([_post("https://x.io/api/first", json.dumps({"a": OPAQUE}), sec=0),
                     _post("https://x.io/api/second", json.dumps({"b": OPAQUE}), sec=1),
                     _get(f"https://x.io/api/use/{OPAQUE}", sec=2)])
    _assert_correlated(res, xml, OPAQUE)
    d = [c for c in res.correlations if c.value == OPAQUE][0]
    assert d.producer_index == 0, "the earliest producer must be chosen"


# ---- name-independence + no false positives -------------------------------------------------------

def test_completely_unfamiliar_field_names_still_correlate():
    # neither producer nor consumer field name is a known id/token word — dependency is by VALUE only
    res, xml = _run([_post("https://x.io/api/flurb", json.dumps({"zorptWibble": OPAQUE})),
                     _consume_body("https://x.io/api/glorp", {"quuxSnarf": OPAQUE})])
    _assert_correlated(res, xml, OPAQUE)


def test_user_supplied_business_input_is_not_correlated():
    # a client-typed value that also happens to appear later must NOT be turned into a correlation
    res, _ = _run([
        {"startedDateTime": "2024-01-01T10:00:00.000Z", "time": 30,
         "request": {"method": "POST", "url": "https://x.io/api/signin", "cookies": [], "queryString": [],
                     "headers": [{"name": "Content-Type", "value": "application/json"}],
                     "postData": {"mimeType": "application/json", "text": json.dumps({"email": "bob@corp.com"})}},
         "response": {"status": 200, "headers": [], "cookies": [],
                      "content": {"mimeType": "application/json", "text": "{}"}}},
        _consume_body("https://x.io/api/profile", {"email": "bob@corp.com"}, sec=1),
    ])
    assert all(c.value != "bob@corp.com" for c in res.correlations), \
        "a user-supplied business input must never be correlated"
