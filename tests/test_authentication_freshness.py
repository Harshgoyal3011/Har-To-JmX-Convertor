"""Synthetic authentication mechanics; real DummyJSON validation is separate."""

import json
import re
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from har2jmx.emit import build_jmx_xml
from har2jmx.engine import analyze
from har2jmx.validate import verify_extractors

TOKEN = "freshRuntimeToken9aBcD123"
REFRESH = "freshRefreshValue9aBcD123"


def entry(method, path, *, body=None, response=None, response_headers=(), headers=(), cookies=(), index=0):
    req = {
        "method": method,
        "url": "https://auth.example" + path,
        "headers": [{"name": n, "value": v} for n, v in headers],
        "cookies": [{"name": n, "value": v} for n, v in cookies],
    }
    if body is not None:
        req["postData"] = {"mimeType": "application/json", "text": json.dumps(body)}
    return {
        "startedDateTime": f"2026-01-01T00:00:{index:02}.000Z",
        "time": 10,
        "request": req,
        "response": {
            "status": 200,
            "headers": [{"name": n, "value": v} for n, v in response_headers],
            "content": {"mimeType": "application/json", "text": json.dumps(response or {})},
        },
    }


def plan(entries):
    result = analyze({"log": {"version": "1.2", "entries": entries}})
    xml = build_jmx_xml(result).decode()
    return result, xml, ET.fromstring(xml)


def cookie_plan(wire=TOKEN, consumer=TOKEN, extra=(), header_name="Set-Cookie"):
    return plan(
        [
            entry(
                "POST",
                "/login",
                body={"username": "loaduser", "password": "Secret123"},
                response_headers=[(header_name, "accessToken=" + wire), *extra],
            ),
            entry(
                "GET",
                "/profile",
                headers=[("Authorization", "Bearer " + consumer)],
                cookies=[("accessToken", consumer)],
                index=1,
            ),
        ]
    )


@pytest.mark.parametrize(
    "suffix",
    ["", "; Path=/; HttpOnly; Secure; SameSite=Lax", "; Expires=Wed, 21 Oct 2026 07:28:00 GMT; Path=/"],
)
@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_cookie_boundary_in_actual_emitted_regex(suffix, newline):
    r, xml, doc = cookie_plan(TOKEN + suffix, extra=[("Set-Cookie", "otherCookie=unrelatedValue123; Path=/")])
    assert all(c.ok for c in r.extractor_checks)
    ex = doc.find(".//RegexExtractor")
    regex = ex.find("stringProp[@name='RegexExtractor.regex']").text
    text = newline.join(
        [
            "HTTP/1.1 200 OK",
            "Set-Cookie: accessToken=" + TOKEN + suffix,
            "Set-Cookie: otherCookie=unrelatedValue123; Path=/",
            "X-Next: unrelated",
        ]
    )
    assert re.search(regex, text).group(1) == TOKEN
    assert TOKEN not in xml and "Bearer ${accessToken}" in xml
    assert "NOT_FOUND_accessToken" in xml and doc.find(".//JSR223PreProcessor") is not None
    assert doc.find(".//JSR223Assertion") is not None


def test_case_insensitive_header_case_sensitive_cookie_name():
    _, xml, doc = cookie_plan(header_name="sEt-CoOkIe", extra=[("Set-Cookie", "AccessToken=wrongValue123")])
    regex = doc.find(".//stringProp[@name='RegexExtractor.regex']").text
    text = "Set-Cookie: AccessToken=wrongValue123\nsEt-CoOkIe:\taccessToken=" + TOKEN + "\nX: last"
    assert re.search(regex, text).group(1) == TOKEN
    assert TOKEN not in xml


def test_quoted_cookie_preserves_wire_delimiters():
    r, xml, doc = cookie_plan('"' + TOKEN + '"; Path=/', consumer='"' + TOKEN + '"')
    regex = doc.find(".//stringProp[@name='RegexExtractor.regex']").text
    assert re.search(regex, 'Set-Cookie: accessToken="' + TOKEN + '"; Path=/').group(1) == '"' + TOKEN + '"'
    assert all(c.ok for c in r.extractor_checks) and TOKEN not in xml


def test_encoded_cookie_uses_logical_variable_and_preserves_wire_encoding():
    logical = "freshRuntimeToken9aBcD123+suffix/value"
    encoded = "freshRuntimeToken9aBcD123%2Bsuffix%2Fvalue"
    r, xml, doc = cookie_plan(encoded, consumer=logical)
    assert all(c.ok for c in r.extractor_checks)
    assert logical not in xml and encoded not in xml
    assert doc.find(".//JSR223PostProcessor") is not None
    assert "value.replace('+', '%2B')" in xml
    assert "Bearer ${accessToken}" in xml
    # A wire-encoded cookie consumer must explicitly re-encode the logical token.
    _, xml, _ = cookie_plan(encoded, consumer=encoded)
    assert "${__urlencode(${accessToken})}" in xml and encoded not in xml
    # Scheme-prefixed consumers also work without a duplicate request cookie.
    _, xml, _ = plan(
        [
            entry("POST", "/login", response_headers=[("Set-Cookie", "accessToken=" + encoded)]),
            entry("GET", "/profile", headers=[("Authorization", "Bearer " + encoded)], index=1),
        ]
    )
    assert "Bearer ${__urlencode(${accessToken})}" in xml and encoded not in xml


def test_multiple_tokens_and_refresh_chain_materialize_all_consumers():
    refreshed = "secondRuntimeToken9aBcD456"
    r, xml, doc = plan(
        [
            entry(
                "POST",
                "/login",
                body={"username": "loaduser", "password": "Secret123"},
                response_headers=[
                    ("Set-Cookie", "accessToken=" + TOKEN),
                    ("Set-Cookie", "refreshToken=" + REFRESH),
                ],
            ),
            entry("GET", "/profile", headers=[("Authorization", "Bearer " + TOKEN)], index=1),
            entry(
                "POST",
                "/auth/refresh",
                body={"refreshToken": REFRESH},
                response={"accessToken": refreshed},
                index=2,
            ),
            entry("GET", "/profile", headers=[("Authorization", "Bearer " + refreshed)], index=3),
        ]
    )
    assert all(c.ok for c in r.extractor_checks)
    assert {c.value for c in r.correlations} == {TOKEN, REFRESH, refreshed}
    for c in r.correlations:
        assert c.value not in xml and "${" + c.variable + "}" in xml
    assert len(doc.findall(".//RegexExtractor")) == 2 and len(doc.findall(".//JSONPostProcessor")) == 1
    cols = {c.name for d in r.parameterization.datasets for c in d.columns}
    assert {"username", "password"} <= cols


@pytest.mark.parametrize("header", ["X-CSRF-Token", "X-Auth-Token", "X-Custom-Authentication"])
def test_response_header_state_to_custom_authentication_header(header):
    r, xml, doc = plan(
        [
            entry("POST", "/login", response_headers=[(header, TOKEN)]),
            entry("POST", "/business", body={"quantity": 2}, headers=[(header, TOKEN)], index=1),
        ]
    )
    assert r.correlations and all(c.ok for c in r.extractor_checks)
    assert TOKEN not in xml and "${" + r.correlations[0].variable + "}" in xml
    assert doc.find(".//RegexExtractor") is not None
    assert doc.find(".//JSR223Assertion") is not None


def test_session_only_cookie_uses_thread_local_cookie_manager():
    r, xml, doc = plan(
        [
            entry(
                "POST", "/login", response_headers=[("Set-Cookie", "session=" + TOKEN + "; Path=/; HttpOnly")]
            ),
            entry("GET", "/profile", cookies=[("session", TOKEN)], index=1),
        ]
    )
    assert any(c.extractor.value == "cookie_manager" for c in r.correlations)
    assert TOKEN not in xml and not doc.findall(".//RegexExtractor")
    assert doc.find(".//boolProp[@name='CookieManager.clearEachIteration']").text == "true"
    assert not doc.findall(".//Cookie")


def test_validation_failure_blocks_authentication_without_stale_literal():
    r, _, _ = cookie_plan()
    r.capture.requests[0].response.headers = []
    r.capture.requests[0].response.set_cookies = []
    r.extractor_checks = verify_extractors(r.capture, r.correlations)
    assert not r.extractor_checks[0].ok
    xml = build_jmx_xml(r).decode()
    doc = ET.fromstring(xml)
    assert TOKEN not in xml and "Bearer ${accessToken}" in xml
    assert not doc.findall(".//RegexExtractor")
    script = doc.find(".//JSR223Assertion/stringProp[@name='script']").text
    assert "AssertionResult.setFailure(true)" in script and "prev.setStopThread(true)" in script
    assert "NOT_FOUND_" in doc.find(".//JSR223PreProcessor/stringProp[@name='script']").text


def test_unused_and_superseded_tokens_do_not_gain_extractors():
    unused = "unusedRuntimeToken9aBcD111"
    old = "supersededToken9aBcD222"
    r, xml, doc = plan(
        [
            entry("POST", "/login", response={"accessToken": old, "refreshToken": unused}),
            entry("POST", "/login", response={"accessToken": TOKEN}, index=1),
            entry("GET", "/profile", headers=[("Authorization", "Bearer " + TOKEN)], index=2),
        ]
    )
    assert {c.value for c in r.correlations} == {TOKEN}
    assert len(doc.findall(".//JSONPostProcessor")) == 1
    assert old not in xml and unused not in xml and TOKEN not in xml


def test_supported_oauth_redirect_code_and_token_keep_existing_materialization():
    result = analyze((Path(__file__).parent / "fixtures/sample_oauth.har").read_bytes())
    xml = build_jmx_xml(result).decode()
    doc = ET.fromstring(xml)
    assert "${code}" in xml and "${access_token}" in xml
    assert "AUTHCODE-9f8e7d6c5b4a3210" not in xml
    assert doc.find(".//RegexExtractor") is not None
    assert 'follow_redirects">false' in xml


def test_otp_stays_parameter_and_challenge_stays_runtime():
    r, xml, doc = plan(
        [
            entry(
                "POST",
                "/login",
                body={"username": "loaduser", "password": "Secret123"},
                response={"challengeId": TOKEN},
            ),
            entry(
                "POST",
                "/auth/mfa",
                body={"challengeId": TOKEN, "otp": "123456"},
                response={"accessToken": REFRESH},
                index=1,
            ),
            entry("GET", "/profile", headers=[("Authorization", "Bearer " + REFRESH)], index=2),
        ]
    )
    cols = {c.name for d in r.parameterization.datasets for c in d.columns}
    assert {"username", "password", "otp"} <= cols
    assert {c.value for c in r.correlations} == {TOKEN, REFRESH}
    assert "${otp}" in xml and TOKEN not in xml and REFRESH not in xml
    assert len(doc.findall(".//JSONPostProcessor")) == 2


def test_auth_state_is_thread_local_and_reset_at_each_producer():
    _, xml, doc = cookie_plan()
    scripts = [p.text for p in doc.findall(".//stringProp[@name='script']")]
    assert any("vars.put" in s for s in scripts)
    assert not any("props." in s or "static " in s for s in scripts)
    assert TOKEN not in xml
    parents = {c: p for p in doc.iter() for c in p}
    for component in doc.findall(".//JSR223PreProcessor") + doc.findall(".//JSR223Assertion"):
        subtree = parents[component]
        siblings = list(parents[subtree])
        assert siblings[siblings.index(subtree) - 1].tag == "HTTPSamplerProxy"


def test_pagination_token_does_not_gain_authentication_components():
    r, xml, doc = plan(
        [
            entry("GET", "/catalog", response={"nextPageToken": TOKEN}),
            entry("GET", "/catalog?nextPageToken=" + TOKEN, index=1),
        ]
    )
    assert r.correlations and TOKEN not in xml
    assert not doc.findall(".//JSR223PreProcessor")
    assert not any(n.get("testname") == "Require fresh authentication state" for n in doc.iter())
