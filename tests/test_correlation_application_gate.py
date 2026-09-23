"""Release gate: a VERIFIED-UNIQUE, substitutable correlation must be applied (its ${var} present in a
consumer). Distinct from validate_plan's "literal shipped" substring check; unverifiable extractors are
intentional safe-drops, not defects. Proven on the frozen real corpus to have zero genuine violations."""
from __future__ import annotations

import json

from har2jmx.emit import build_jmx_xml
from har2jmx.engine import analyze
from release_gate import evaluate

_GATE = "verified-unique correlation is applied to a consumer (${var} present)"


def _server_id_flow():
    entries = [
        {"pageref": "p1", "startedDateTime": "2024-01-01T10:00:00.000Z", "time": 40,
         "request": {"method": "POST", "url": "https://app.example.com/api/orders",
                     "headers": [{"name": "Content-Type", "value": "application/json"}], "cookies": [],
                     "postData": {"mimeType": "application/json", "text": json.dumps({"item": "widget"})}},
         "response": {"status": 201, "headers": [{"name": "Content-Type", "value": "application/json"}],
                      "cookies": [], "content": {"mimeType": "application/json", "text": '{"orderId":"ORD-77123"}'}}},
        {"pageref": "p1", "startedDateTime": "2024-01-01T10:00:00.500Z", "time": 40,
         "request": {"method": "GET", "url": "https://app.example.com/api/orders/ORD-77123",
                     "headers": [], "cookies": []},
         "response": {"status": 200, "headers": [{"name": "Content-Type", "value": "application/json"}],
                      "cookies": [], "content": {"mimeType": "application/json", "text": '{"orderId":"ORD-77123","status":"ok"}'}}},
    ]
    res = analyze(json.dumps({"log": {"version": "1.2", "entries": entries}}).encode())
    return res, build_jmx_xml(res, {"threads": "5"}).decode()


def _gate(res, xml):
    return next(g for g in evaluate(res, xml) if g.name == _GATE)


def test_gate_passes_when_verified_correlation_is_applied():
    res, xml = _server_id_flow()
    assert "/api/orders/${orderId}" in xml            # correlated into the consumer path
    assert _gate(res, xml).passed


def test_gate_fails_when_verified_correlation_not_applied():
    # simulate an emission bug: the verified extractor stays, but the ${var} is not applied to the consumer
    res, xml = _server_id_flow()
    broken = xml.replace("${orderId}", "ORD-77123")   # variable dropped, literal shipped instead
    assert "${orderId}" not in broken
    gr = _gate(res, broken)
    assert not gr.passed, gr.detail
