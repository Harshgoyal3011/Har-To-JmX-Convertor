"""Synthetic role mechanics plus separately labeled original real captures."""

import json
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from har2jmx.classify import ValueClass
from har2jmx.emit import build_jmx_xml
from har2jmx.engine import analyze


def exchange(path, response, *, mime="application/json", method="GET", headers=(), body=None, index=0):
    request = {"method": method, "url": "https://retention.example" + path,
               "headers": [{"name": k, "value": v} for k, v in headers]}
    if body is not None:
        request["postData"] = {"mimeType": "application/json", "text": json.dumps(body)}
    return {
        "startedDateTime": f"2026-01-01T10:00:{index:02}.000Z", "time": 5,
        "request": request,
        "response": {"status": 200, "headers": [], "content": {
            "mimeType": mime, "text": json.dumps(response) if isinstance(response, (dict, list)) else response,
        }},
    }


def plan(entries):
    result = analyze({"log": {"entries": entries}})
    return result, ET.fromstring(build_jmx_xml(result))


@pytest.mark.parametrize("path", ["/asset/record", "/images/records", "/media/records", "/photos/records", "/assets/records"])
def test_data_record_collection_survives_static_path_vocabulary(path):
    result, doc = plan([exchange(path, {"entries": [{"unfamiliar": "R42", "caption": "Selected item"}]})])
    assert not result.capture.requests[0].classification.excluded
    assert result.capture.requests[0].classification.business_candidate
    assert len(doc.findall(".//HTTPSamplerProxy")) == 1


@pytest.mark.parametrize("mime", ["application/json", "application/geo+json", "application/json;odata.metadata=minimal"])
def test_content_contract_combines_with_record_collection_not_just_json_mime(mime):
    result, doc = plan([exchange("/media/records", {"value": [{"identity": "R42", "state": "Available"}]}, mime=mime)])
    assert not result.capture.requests[0].classification.excluded
    assert len(doc.findall(".//HTTPSamplerProxy")) == 1


def test_self_describing_hypermedia_catalog_can_link_binary_resources():
    path = "/asset/R42"
    payload = {"collection": {"href": "http://retention.example" + path,
                             "items": [{"href": "https://files.example/file.jpg"}]}}
    result, doc = plan([exchange(path, payload)])
    assert not result.capture.requests[0].classification.excluded
    assert "resource/link catalog" in " ".join(result.capture.requests[0].classification.reasons)
    assert len(doc.findall(".//HTTPSamplerProxy")) == 1


def test_hateoas_relative_navigation_controls_are_application_data():
    payload = {"_links": {"self": {"href": "/media/current"}, "next": {"href": "/media/next"}}}
    result, doc = plan([exchange("/media/current", payload)])
    assert not result.capture.requests[0].classification.excluded
    assert len(doc.findall(".//HTTPSamplerProxy")) == 1


@pytest.mark.parametrize("mime", ["application/xml", "application/soap+xml"])
def test_xml_records_with_data_query_role_are_retained(mime):
    result, doc = plan([exchange("/media/lookup?selection=R42", "<records><record><key>R42</key><label>Item</label></record></records>", mime=mime)])
    assert not result.capture.requests[0].classification.excluded
    assert len(doc.findall(".//HTTPSamplerProxy")) == 1


def test_graphql_api_under_static_looking_path_is_retained():
    result, doc = plan([exchange("/assets/graphql", {"data": {"records": [{"id": "R42", "label": "Item"}]}},
                                method="POST", body={"query": "query Read { records { id label } }"})])
    assert not result.capture.requests[0].classification.excluded
    assert result.classification.by_value("R42").classification == ValueClass.BUSINESS_MASTER_DATA
    assert len(doc.findall(".//HTTPSamplerProxy")) == 1


def test_unknown_field_record_with_actual_request_selector_is_retained():
    result, doc = plan([exchange("/media/R42", {"opaque": "R42", "displayValue": "Available"})])
    assert not result.capture.requests[0].classification.excluded
    assert len(doc.findall(".//HTTPSamplerProxy")) == 1


def test_nested_singleton_record_with_data_query_role_is_retained():
    result, doc = plan([exchange("/media/R42", {"result": {"key": "R42", "displayValue": "Available"}})])
    assert not result.capture.requests[0].classification.excluded
    assert len(doc.findall(".//HTTPSamplerProxy")) == 1


@pytest.mark.parametrize("payload", [{"value": "http://[invalid", "another": "value"},
                                     {"_links": {"self": {"href": "http://[invalid"}, "next": {"href": "/next"}}}])
def test_invalid_url_like_content_does_not_crash_role_classification(payload):
    result, doc = plan([exchange("/assets/config", payload)])
    assert result.capture.requests[0].classification.excluded
    assert not doc.findall(".//HTTPSamplerProxy")


@pytest.mark.parametrize("payload", [{}, [], {"ok": True}, {"fetchStart": 123, "responseStart": 456},
                                     {"endpoint": "https://api.example", "enabled": True}, "{not-json"])
def test_structured_or_json_typed_payload_alone_does_not_override_static_path(payload):
    result, doc = plan([exchange("/assets/bootstrap?cache=123", payload)])
    assert result.capture.requests[0].classification.excluded
    assert not doc.findall(".//HTTPSamplerProxy")


@pytest.mark.parametrize("path", ["/telemetry/media/collect", "/rum/assets/records", "/assets/collect"])
def test_known_telemetry_wins_even_with_business_shaped_structured_content(path):
    result, doc = plan([exchange(path, {"entries": [{"identity": "R42", "label": "Observed"}]}, method="POST")])
    assert result.capture.requests[0].classification.telemetry_candidate
    assert result.capture.requests[0].classification.excluded
    assert not doc.findall(".//HTTPSamplerProxy")


@pytest.mark.parametrize("headers", [[("Sec-Fetch-Dest", "image")], [("Sec-Fetch-Mode", "no-cors")]])
def test_render_or_beacon_transport_role_wins_over_record_shape(headers):
    result, doc = plan([exchange("/assets/probe", {"entries": [{"identity": "R42", "label": "Observed"}]}, headers=headers)])
    assert result.capture.requests[0].classification.excluded
    assert not doc.findall(".//HTTPSamplerProxy")


@pytest.mark.parametrize("path,mime,payload", [
    ("/images/icon.svg", "image/svg+xml", "<svg><g><path>value</path></g></svg>"),
    ("/media/render", "image/png", '{"entries":[{"key":"R42","value":"Observed"}]}'),
    ("/assets/library.js", "application/javascript", 'const data = {"entries": []};'),
    ("/assets/page", "text/html", "<html><body><title>Page</title><p>text</p></body></html>"),
])
def test_actual_rendering_assets_and_documents_remain_filtered(path, mime, payload):
    result, doc = plan([exchange(path, payload, mime=mime)])
    assert result.capture.requests[0].classification.excluded
    assert not doc.findall(".//HTTPSamplerProxy")


@pytest.mark.parametrize("workflow", ["nasa-images-1", "nasa-images-2"])
def test_original_real_nasa_capture_keeps_asset_catalog_in_final_jmx(workflow):
    path = Path(__file__).resolve().parents[2] / "real-world-benchmark/raw" / (workflow + ".har")
    if not path.exists():
        pytest.skip("Original external real benchmark capture is not present")
    result = analyze(path.read_bytes())
    doc = ET.fromstring(build_jmx_xml(result))
    assert not result.capture.requests[1].classification.excluded
    assert not result.correlations
    samplers = doc.findall(".//HTTPSamplerProxy")
    assert len(samplers) == 2
    assert samplers[1].find("stringProp[@name='HTTPSampler.path']").text.startswith("/asset/")
    assert len(doc.findall(".//ResponseAssertion")) == 2
