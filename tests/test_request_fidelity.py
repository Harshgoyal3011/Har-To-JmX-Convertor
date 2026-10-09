"""Final JMX URL ownership and body ownership, independent of analyzer policy."""
import json
from dataclasses import asdict
from urllib.parse import parse_qsl, urlsplit
from xml.etree import ElementTree as ET

import pytest

from har2jmx.emit import build_jmx_xml
from har2jmx.emit.jmx import _add_http_sampler
from har2jmx.engine import analyze
from har2jmx.ir.build import build_capture as build_ir
from har2jmx.parameterize import ParameterColumn, ParameterDataset, ParameterizationPlan, ParameterSlot


def entry(method="POST", query="tenant=acme", mime="application/json", body=None):
    request = {"method": method, "url": "http://example.test/api/data" + ("?" + query if query else ""),
               "headers": [], "cookies": []}
    if mime:
        request["headers"] = [{"name": "Content-Type", "value": mime}]
        request["postData"] = {"mimeType": mime, "text": body if body is not None else json.dumps({"qty": 3})}
    return {"startedDateTime": "2026-01-01T10:00:00Z", "time": 1, "request": request,
            "response": {"status": 200, "headers": [], "content": {"mimeType": "application/json", "text": "{}"}}}


def sampler(e, sub=None, slots=None):
    req = build_ir({"log": {"entries": [e]}}).requests[0]
    root = ET.Element("hashTree")
    _add_http_sampler(root, req, sub or {}, slot_subs=slots or [])
    # Serialize and load the final emitted XML, rather than inspecting IR.
    return ET.fromstring(ET.tostring(root)), req


def prop(root, name):
    return root.findtext(f".//*[@name='{name}']") or ""


def arguments(root):
    return [{child.get("name"): child.text or "" for child in arg}
            for arg in root.findall(".//elementProp[@elementType='HTTPArgument']")]


@pytest.mark.parametrize("method,mime,body,raw", [
    ("GET", "", "", False), ("HEAD", "", "", False),
    ("POST", "application/json", json.dumps({"qty": 3}), True),
    ("POST", "application/json", json.dumps({"query": "query Items { items { id } }", "variables": {"qty": 3}}), True),
    ("POST", "application/xml", "<qty>3</qty>", True),
    ("POST", "text/xml", "<soap:Envelope><qty>3</qty></soap:Envelope>", True),
    ("POST", "text/plain", "quantity=3", True),
    ("POST", "application/x-www-form-urlencoded", "name=Alice", False),
    ("PUT", "application/json", json.dumps({"qty": 3}), True),
    ("PATCH", "application/json", json.dumps({"qty": 3}), True),
])
def test_query_and_body_owners_by_representation(method, mime, body, raw):
    root, _ = sampler(entry(method, mime=mime, body=body))
    assert prop(root, "HTTPSampler.path") == "/api/data?tenant=acme"
    assert parse_qsl(urlsplit(prop(root, "HTTPSampler.path")).query) == [("tenant", "acme")]
    args = arguments(root)
    assert all(a.get("Argument.name") != "tenant" for a in args)
    assert prop(root, "HTTPSampler.postBodyRaw") == str(raw).lower()
    if raw:
        assert len(args) == 1 and args[0]["Argument.value"] == body
        assert args[0]["HTTPArgument.always_encode"] == "false"
    elif mime:
        assert [(a["Argument.name"], a["Argument.value"]) for a in args] == [("name", "Alice")]
        assert args[0]["HTTPArgument.always_encode"] == "true"
    else:
        assert args == []
    assert prop(root, "Header.value") == mime


@pytest.mark.parametrize("query", [
    "tag=one&tag=two&tag=one", "empty=&flag&=value&&last=",
    "q=a%20b%2fc%2B%26%3D%3F%23&symbol=%25&utf=%E9%9B%AA",
    "q=one+two&reserved=/%3F:@!%24%26%3D", "",
])
def test_static_query_spelling_order_repeats_and_empty_values(query):
    root, _ = sampler(entry(query=query))
    assert prop(root, "HTTPSampler.path") == "/api/data" + ("?" + query if query else "")
    assert len(arguments(root)) == 1
    assert arguments(root)[0]["Argument.value"] == json.dumps({"qty": 3})


def test_ir_query_is_authoritative_when_url_spelling_differs():
    e = entry(query="tenant=old")
    req = build_ir({"log": {"entries": [e]}}).requests[0]
    req.request.query = [("tenant", "new & value"), ("tenant", "")]
    root = ET.Element("hashTree")
    _add_http_sampler(root, req, {})
    assert prop(root, "HTTPSampler.path") == "/api/data?tenant=new+%26+value&tenant="


def test_equal_query_and_body_literals_stay_in_separate_slots():
    root, _ = sampler(entry(body=json.dumps({"tenant": "acme"})),
                      slots=[("acme", "url_owner", frozenset({"request.query:tenant"})),
                             ("acme", "body_owner", frozenset({"request.body:tenant"}))])
    assert prop(root, "HTTPSampler.path") == "/api/data?tenant=${__urlencode(${url_owner})}"
    assert arguments(root)[0]["Argument.value"] == json.dumps({"tenant": "${body_owner}"})


def test_multipart_query_is_not_a_part():
    e = entry(mime="multipart/form-data", body="")
    e["request"]["postData"]["params"] = [
        {"name": "name", "value": "Alice"},
        {"name": "upload", "fileName": "payload.txt", "contentType": "text/plain"},
    ]
    root, _ = sampler(e)
    assert prop(root, "HTTPSampler.path") == "/api/data?tenant=acme"
    assert prop(root, "HTTPSampler.DO_MULTIPART_POST") == "true"
    assert [(a["Argument.name"], a["Argument.value"]) for a in arguments(root)] == [("name", "Alice")]
    assert prop(root, "File.path") == "payload.txt"
    assert prop(root, "File.paramname") == "upload"


def test_runtime_query_is_encoded_after_substitution():
    root, _ = sampler(entry(), sub={"acme": "${tenant}"})
    assert prop(root, "HTTPSampler.path") == "/api/data?tenant=${__urlencode(${tenant})}"
    assert arguments(root)[0]["Argument.value"] == json.dumps({"qty": 3})


def test_approved_csv_bindings_survive_full_plan_emission():
    result = analyze({"log": {"entries": [entry(body=json.dumps({"name": "Alice"}))]}})
    columns = []
    for field, value, location in [("tenant", "acme", "query"), ("name", "Alice", "body")]:
        slot = ParameterSlot(0, f"request.{location}:{field}", location, field, value, value, "POST")
        columns.append(ParameterColumn(field, value, intent="USER_INPUT", logical_field=field,
                                       original=value, normalized=value, slots=[slot]))
    result.parameterization = ParameterizationPlan([ParameterDataset("Inputs", columns,
        [{"tenant": "acme", "name": "Alice"}], "inputs")])
    frozen = asdict(result.parameterization)
    root = ET.fromstring(build_jmx_xml(result))
    assert prop(root, "HTTPSampler.path") == "/api/data?tenant=${__urlencode(${tenant})}"
    assert arguments(root)[0]["Argument.value"] == json.dumps({"name": "${name}"})
    assert asdict(result.parameterization) == frozen


def test_redirect_location_owns_query_while_body_is_preserved():
    req = build_ir({"log": {"entries": [entry(mime="application/x-www-form-urlencoded", body="name=Alice")]}}).requests[0]
    root = ET.Element("hashTree")
    _add_http_sampler(root, req, {}, redirect_target="${__har2jmx_redirect_0}")
    assert prop(root, "HTTPSampler.path") == "${__har2jmx_redirect_0}"
    assert [(a["Argument.name"], a["Argument.value"]) for a in arguments(root)] == [("name", "Alice")]
