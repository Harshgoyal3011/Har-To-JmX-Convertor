"""Causal boundaries and final JMX membership, not one controller per endpoint."""
from __future__ import annotations

import json
from xml.etree import ElementTree as ET

from har2jmx.classify import classify_capture
from har2jmx.engine import analyze
from har2jmx.ir.build import build_capture
from har2jmx.workflow import discover_transactions
from har2jmx.workflow.naming import tokenize


def _entry(path, seconds, *, document=False, listener="", response=None, redirect=""):
    headers = []
    if document:
        headers = [{"name": key, "value": value} for key, value in {
            "Sec-Fetch-User": "?1", "Sec-Fetch-Dest": "document", "Sec-Fetch-Mode": "navigate",
        }.items()]
    return {
        "startedDateTime": f"2026-01-01T00:00:{seconds:06.3f}Z", "time": 100, "pageref": "same_page",
        "_resourceType": "document" if document else "xhr", "_frameref": "main",
        "_initiator": {"type": "script", "stack": {"callFrames": [{
            "functionName": listener, "url": "https://example.test/app.js", "lineNumber": 10, "columnNumber": 20,
        }]}} if listener else {},
        "request": {"method": "GET", "url": "https://example.test" + path, "headers": headers},
        "response": {"status": 302 if redirect else 200,
                     "headers": [{"name": "Location", "value": redirect}] if redirect else [],
                     "content": {"mimeType": "application/json", "text": json.dumps(response or {})}},
    }


def _capture(entries):
    cap = build_capture({"log": {"entries": entries}})
    classify_capture(cap)
    return cap


def test_fast_user_navigation_has_boundary_with_same_pageref():
    cap = _capture([_entry("/catalog", 0, document=True), _entry("/orders", .2, document=True)])
    txns = discover_transactions(cap)
    assert [t.request_indices for t in txns] == [[0], [1]]
    assert txns[1].boundary_confidence == "supported"


def test_redirect_target_does_not_create_interaction():
    cap = _capture([_entry("/start", 0, document=True, redirect="/catalog"),
                    _entry("/catalog", .2, document=True), _entry("/catalog/facets", .4)])
    txns = discover_transactions(cap)
    assert [t.request_indices for t in txns] == [[0, 1, 2]]


def test_same_listener_many_requests_stays_one_interaction():
    cap = _capture([_entry("/catalog", 0, listener="Menu_click_listener"),
                    _entry("/catalog/facets", .2, listener="Menu_click_listener"),
                    _entry("/permissions", .3, listener="Menu_click_listener")])
    txns = discover_transactions(cap)
    assert [t.request_indices for t in txns] == [[0, 1, 2]]


def test_changed_event_listener_supports_new_interaction_without_gap():
    cap = _capture([_entry("/catalog", 0, listener="Menu_click_listener"),
                    _entry("/catalog/facets", .2, listener="Menu_click_listener"),
                    _entry("/orders", .3, listener="Order_submit_listener")])
    txns = discover_transactions(cap)
    assert [t.request_indices for t in txns] == [[0, 1], [2]]
    assert txns[1].boundary_reasons == ["changed_explicit_event_listener_call_site"]


def test_endpoint_change_or_long_gap_is_not_proven_ui_action():
    cap = _capture([_entry("/catalog", 0), _entry("/facets", .2), _entry("/permissions", 10)])
    txns = discover_transactions(cap)
    assert txns[0].request_indices == [0, 1]
    assert txns[1].boundary_confidence == "uncertain"


def test_iframe_is_not_top_level_navigation():
    entries = [_entry("/catalog", 0), _entry("/iframe", .2, document=True)]
    entries[1]["request"]["headers"][1]["value"] = "iframe"
    assert len(discover_transactions(_capture(entries))) == 1


def test_repeated_operations_share_name_keep_distinct_controllers():
    cap = _capture([_entry("/getDoctorList", 0, document=True),
                    _entry("/getDoctorList", .2, document=True)])
    txns = discover_transactions(cap)
    assert len(txns) == 2
    assert [t.name for t in txns] == ["View Doctor List", "View Doctor List"]


def test_final_jmx_preserves_sampler_order_and_bodies(tmp_path):
    from har2jmx.emit import emit_jmx

    entries = [_entry("/getDoctorList", 0, document=True), _entry("/lookup", .1),
               _entry("/getWardBedDetails", .2, document=True)]
    result = analyze({"log": {"entries": entries}})
    path, _, _ = emit_jmx(result, tmp_path, {"threads": "1", "loops": "1", "ramp": "0"})
    doc = ET.parse(path).getroot()
    assert [n.get("testname") for n in doc.iter("TransactionController")] == ["View Doctor List", "View Ward Bed Details"]
    assert [n.get("testname") for n in doc.iter("HTTPSamplerProxy")] == [
        "GET /getDoctorList", "GET /lookup", "GET /getWardBedDetails"]
    assert [t.request_indices for t in result.transactions] == [[0, 1], [2]]


def test_parser_retains_context_without_changing_request_data():
    cap = _capture([_entry("/catalog", 0, listener="Menu_click_listener")])
    request = cap.requests[0]
    assert request.context.resource_type == "xhr"
    assert request.context.frame_ref == "main"
    assert request.context.initiator_detail["stack"]["callFrames"][0]["functionName"] == "Menu_click_listener"
    assert request.request.url == "https://example.test/catalog"


def test_generic_tokenization_preserves_acronyms_and_explicit_boundaries():
    assert tokenize("getHTTPStatus") == ["get", "HTTP", "Status"]
    assert tokenize("SavePatientAdmissionAdvice") == ["Save", "Patient", "Admission", "Advice"]
    assert tokenize("ward_bed-details") == ["ward", "bed", "details"]


def test_operation_name_does_not_invent_write_prefix():
    cap = _capture([_entry("/booking", 0)])
    assert discover_transactions(cap)[0].name == "View Booking"


def test_camel_case_save_action_not_transport_create():
    entry = _entry("/saveAdmissionAdvice", 0)
    entry["request"]["method"] = "POST"
    txns = discover_transactions(_capture([entry]))
    assert txns[0].name == "Save Admission Advice"
    assert txns[0].category == "Business Action"
