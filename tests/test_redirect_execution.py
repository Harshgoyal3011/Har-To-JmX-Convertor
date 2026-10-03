"""Synthetic redirect mechanics, inspected in the final generated JMX."""

from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from har2jmx.emit import build_jmx_xml, validate_plan
from har2jmx.engine import analyze
from har2jmx.parameterize.decide import ParameterColumn, ParameterDataset
from har2jmx.parameterize.intent import ParameterSlot


def entry(path, status=200, location="", *, method="GET", headers=(), body="", index=0):
    request = {
        "method": method,
        "url": "https://redirect.example" + path,
        "headers": [{"name": n, "value": v} for n, v in headers],
        "cookies": [],
    }
    if body:
        request["postData"] = {"mimeType": "application/json", "text": body}
    return {
        "startedDateTime": f"2026-01-01T00:00:{index:02}.000Z",
        "time": 10,
        "request": request,
        "response": {
            "status": status,
            "headers": [{"name": "Location", "value": location}] if location else [],
            "content": {"mimeType": "application/json", "text": body or "{}"},
        },
    }


def plan(entries):
    result = analyze({"log": {"version": "1.2", "entries": entries}})
    # These fixtures exercise redirect transport with fixed scenario routes.
    # Parameterization policy is tested separately and is not changed by P1-2.
    result.parameterization.datasets = []
    xml = build_jmx_xml(result).decode()
    return result, xml, ET.fromstring(xml)


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
def test_static_get_redirect_follows_once_without_duplicate_sampler(status):
    _, xml, doc = plan([entry("/start", status, "/home"), entry("/home", index=1)])
    samplers = doc.findall(".//HTTPSamplerProxy")
    assert len(samplers) == 1
    assert samplers[0].find("boolProp[@name='HTTPSampler.follow_redirects']").text == "true"
    assert "/home" not in xml and not doc.findall(".//RegexExtractor")


def test_runtime_session_location_is_followed_without_captured_target():
    _, xml, doc = plan(
        [
            entry("/api/catalog", 302, "/api/(S(capturedSession123))/catalog"),
            entry("/api/(S(capturedSession123))/catalog", index=1),
        ]
    )
    assert "capturedSession123" not in xml
    assert len(doc.findall(".//HTTPSamplerProxy")) == 1


def test_multistep_chain_has_one_authoritative_follower():
    _, xml, doc = plan(
        [
            entry("/start", 302, "/middle", index=0),
            entry("/middle", 301, "/final", index=1),
            entry("/final", index=2),
        ]
    )
    assert len(doc.findall(".//HTTPSamplerProxy")) == 1
    assert "/middle" not in xml and "/final" not in xml


def test_redirect_without_captured_target_keeps_automatic_following():
    _, _, doc = plan([entry("/start", 302, "/not-recorded")])
    assert len(doc.findall(".//HTTPSamplerProxy")) == 1
    assert doc.find(".//boolProp[@name='HTTPSampler.follow_redirects']").text == "true"


def test_request_specific_header_requires_explicit_current_location():
    result, xml, doc = plan(
        [
            entry("/start", 302, "/(S(capturedSession123))/home"),
            entry("/(S(capturedSession123))/home", headers=[("X-Business-Option", "detail")], index=1),
        ]
    )
    samplers = doc.findall(".//HTTPSamplerProxy")
    assert len(samplers) == 2
    assert samplers[0].find("boolProp[@name='HTTPSampler.follow_redirects']").text == "false"
    assert samplers[1].find("stringProp[@name='HTTPSampler.path']").text == "${__har2jmx_redirect_0}"
    assert "capturedSession123" not in xml
    assert "X-Business-Option" in xml
    assert not validate_plan(result, xml)
    assert doc.find(".//RegexExtractor/stringProp[@name='RegexExtractor.useHeaders']").text == "true"


def test_encoded_redirect_location_keeps_its_wire_encoding():
    _, xml, doc = plan(
        [
            entry("/start", 302, "/(opaque%2Bvalue%2F123)/home"),
            entry("/(opaque%2Bvalue%2F123)/home", headers=[("X-Mode", "full")], index=1),
        ]
    )
    assert "opaque%2Bvalue%2F123" not in xml
    assert (
        doc.findall(".//HTTPSamplerProxy")[1]
        .find("stringProp[@name='HTTPSampler.path']")
        .text.startswith("${")
    )
    assert "toASCIIString()" in xml


def test_multistep_explicit_chain_disables_following_at_every_intermediate():
    _, xml, doc = plan(
        [
            entry("/start", 302, "/middle"),
            entry("/middle", 302, "/final", index=1),
            entry("/final", headers=[("X-Business", "full")], index=2),
        ]
    )
    samplers = doc.findall(".//HTTPSamplerProxy")
    assert len(samplers) == 3
    assert [s.find("boolProp[@name='HTTPSampler.follow_redirects']").text for s in samplers] == [
        "false",
        "false",
        "true",
    ]
    assert "${__har2jmx_redirect_0}" in xml and "${__har2jmx_redirect_1}" in xml


def test_supported_oauth_preserves_p1_auth_extractors_and_explicit_callback():
    result = analyze((Path(__file__).parent / "fixtures/sample_oauth.har").read_bytes())
    xml = build_jmx_xml(result).decode()
    doc = ET.fromstring(xml)
    assert len(doc.findall(".//HTTPSamplerProxy")) == 4
    assert doc.find(".//boolProp[@name='HTTPSampler.follow_redirects']").text == "false"
    assert "${code}" in xml and "${access_token}" in xml
    assert "AUTHCODE-9f8e7d6c5b4a3210" not in xml
    assert any(n.get("testname") == "Require fresh authentication state" for n in doc.iter())
    assert "__har2jmx_redirect_" not in xml


def test_redirect_target_preserves_existing_csv_bindings():
    result = analyze(
        {
            "log": {
                "entries": [
                    entry("/login?username=loaduser", 302, "/profile?username=loaduser"),
                    entry("/profile?username=loaduser", index=1),
                ]
            }
        }
    )
    # Feed an already approved CSV input into emission; do not prescribe or
    # depend on a changed parameterization discovery policy.
    slots = [
        ParameterSlot(
            request_index=i,
            location="request.query:username",
            slot_kind="query",
            field="username",
            original="loaduser",
            normalized="loaduser",
            method="GET",
        )
        for i in [0, 1]
    ]
    result.parameterization.datasets = [
        ParameterDataset(
            "Inputs",
            [
                ParameterColumn(
                    name="username",
                    sample="loaduser",
                    original="loaduser",
                    normalized="loaduser",
                    slots=slots,
                )
            ],
            [{"username": "loaduser"}],
            "inputs",
        )
    ]
    xml = build_jmx_xml(result).decode()
    doc = ET.fromstring(xml)
    assert any(c.name == "username" for d in result.parameterization.datasets for c in d.columns)
    assert xml.count("${username}") == 2
    assert len(doc.findall(".//HTTPSamplerProxy")) == 2
    assert "__har2jmx_redirect_" not in xml
    assert doc.find(".//boolProp[@name='HTTPSampler.follow_redirects']").text == "false"


@pytest.mark.parametrize("status", [307, 308])
def test_method_preserving_post_redirect_keeps_explicit_body(status):
    _, _, doc = plan(
        [
            entry("/submit", status, "/accepted", method="POST", body='{"quantity":2}'),
            entry("/accepted", method="POST", body='{"quantity":2}', index=1),
        ]
    )
    samplers = doc.findall(".//HTTPSamplerProxy")
    assert len(samplers) == 2
    assert all(s.find("stringProp[@name='HTTPSampler.method']").text == "POST" for s in samplers)
    assert samplers[0].find("boolProp[@name='HTTPSampler.follow_redirects']").text == "false"
    assert all(s.find("boolProp[@name='HTTPSampler.postBodyRaw']").text == "true" for s in samplers)


def test_method_preserving_form_redirect_keeps_form_inputs():
    entries = [
        entry("/submit", 307, "/accepted", method="POST"),
        entry("/accepted", method="POST", index=1),
    ]
    for request in entries:
        request["request"]["postData"] = {
            "mimeType": "application/x-www-form-urlencoded",
            "params": [{"name": "quantity", "value": "2"}],
        }
    _, _, doc = plan(entries)
    target = doc.findall(".//HTTPSamplerProxy")[1]
    arguments = target.findall(".//elementProp[@elementType='HTTPArgument']")
    assert [p.find("stringProp[@name='Argument.name']").text for p in arguments] == ["quantity"]
    assert arguments[0].find("stringProp[@name='Argument.value']").text == "2"
    assert target.find("stringProp[@name='HTTPSampler.path']").text == "${__har2jmx_redirect_0}"
