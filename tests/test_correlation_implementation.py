"""A correlation is complete only when the final script binds its consumers."""
from dataclasses import asdict
from pathlib import Path
from urllib.parse import quote
from xml.etree import ElementTree as ET

import pytest

from har2jmx.emit import build_jmx_xml, emit_jmx
from har2jmx.engine import analyze
from har2jmx.ir.normalized import BodyKind
from har2jmx.webreport import build_web_summary

FIX = Path(__file__).parent / "fixtures"


def encoded_result():
    result = analyze((FIX / "sample_saml.har").read_bytes())
    # Include reserved Base64 characters so the recorded params keep escapes.
    for correlation in result.correlations:
        if correlation.variable not in {"SAMLRequest", "SAMLResponse"}:
            continue
        original = correlation.value
        canonical = original + "+/="
        correlation.value = canonical
        response = result.capture.requests[correlation.producer_index].response.body
        response.raw = response.raw.replace(original, canonical)
        for check in result.extractor_checks:
            if check.variable == correlation.variable:
                check.value = canonical
        for index in correlation.consumers:
            body = result.capture.requests[index].request.body
            if correlation.variable == "SAMLRequest":
                body.kind = BodyKind.FORM
                body.form.append((correlation.variable, original))
                request = result.capture.requests[index].request
                request.method = "POST"
                request.query = [(name, value) for name, value in request.query if name != correlation.variable]
            body.form = [(name, quote(canonical, safe="") if name == correlation.variable else value)
                         for name, value in body.form]
    return result


def arg_values(root, name):
    return [arg.findtext("stringProp[@name='Argument.value']") for arg in root.findall(".//elementProp[@elementType='HTTPArgument']")
            if arg.findtext("stringProp[@name='Argument.name']") == name]


def test_encoded_accepted_saml_forms_bind_runtime_variables():
    result = encoded_result()
    frozen = ([asdict(c) for c in result.correlations], asdict(result.classification), asdict(result.parameterization))
    xml = build_jmx_xml(result)
    root = ET.fromstring(xml)
    for name in ["SAMLRequest", "SAMLResponse"]:
        assert arg_values(root, name) == ["${" + name + "}"]
    summary = build_web_summary(result, "probe", {}, xml)
    for name in ["SAMLRequest", "SAMLResponse"]:
        assert summary["correlationImplementation"][name]["implemented"]
    assert frozen == ([asdict(c) for c in result.correlations], asdict(result.classification), asdict(result.parameterization))


def test_encoded_spelling_outside_accepted_consumer_stays_literal():
    result = encoded_result()
    correlation = next(c for c in result.correlations if c.variable == "SAMLRequest")
    raw = quote(correlation.value, safe="")
    # Same raw spelling on an earlier request has no approved dependency.
    result.capture.requests[0].request.body.form.append(("unrelated", raw))
    result.capture.requests[0].request.body.kind = result.capture.requests[correlation.consumers[0]].request.body.kind
    root = ET.fromstring(build_jmx_xml(result))
    assert arg_values(root, "unrelated") == [raw]
    assert arg_values(root, "SAMLRequest") == ["${SAMLRequest}"]


@pytest.mark.parametrize("damage", ["no_reference", "no_extractor", "disabled_extractor", "assertion_only", "wrong_producer"])
def test_ui_does_not_claim_incomplete_correlation(damage):
    result = analyze((FIX / "sample_flow.har").read_bytes())
    root = ET.fromstring(build_jmx_xml(result))
    extractor = next(node for node in root.iter("JSONPostProcessor")
                     if node.findtext("stringProp[@name='JSONPostProcessor.referenceNames']") == "orderId")
    if damage in {"no_reference", "assertion_only"}:
        for sampler in root.iter("HTTPSamplerProxy"):
            for prop in sampler.iter("stringProp"):
                if prop.get("name") in {"Argument.value", "HTTPSampler.path"}:
                    prop.text = (prop.text or "").replace("${orderId}", "literal")
        if damage == "assertion_only":
            ET.SubElement(root, "stringProp", name="assertion.script").text = "${orderId}"
    elif damage == "disabled_extractor":
        extractor.set("enabled", "false")
    elif damage == "wrong_producer":
        parents = {child: parent for parent in root.iter() for child in parent}
        parents[extractor].remove(extractor)
        root.append(extractor)
    else:
        extractor.find("stringProp[@name='JSONPostProcessor.referenceNames']").text = "other"
    xml = ET.tostring(root)
    summary = build_web_summary(result, "probe", {}, xml)
    assert "orderId" not in {c["variable"] for c in summary["correlations"]}
    assert "orderId" in {m["field"] for m in summary["manualCorrelations"]}
    assert not summary["correlationImplementation"]["orderId"]["implemented"]
    assert summary["metrics"]["correlations"] == len(summary["correlations"])


def test_partial_consumer_binding_is_reported_for_review():
    result = analyze((FIX / "sample_flow.har").read_bytes())
    xml = build_jmx_xml(result)
    correlation = next(c for c in result.correlations if c.variable == "orderId")
    correlation.consumers.append(0)
    summary = build_web_summary(result, "probe", {}, xml)
    assert not summary["correlationImplementation"]["orderId"]["implemented"]
    assert "orderId" in {m["field"] for m in summary["manualCorrelations"]}


def test_cookie_manager_remains_an_implemented_mechanism():
    result = analyze((FIX / "sample_saml.har").read_bytes())
    xml = build_jmx_xml(result)
    summary = build_web_summary(result, "probe", {}, xml)
    cookies = [c for c in result.correlations if c.extractor.value == "cookie_manager"]
    assert cookies
    assert all(summary["correlationImplementation"][c.variable]["implemented"] for c in cookies)


def test_downloaded_review_report_matches_incomplete_ui_binding(tmp_path):
    result = analyze((FIX / "sample_flow.har").read_bytes())
    # Keep policy decisions frozen while removing only a captured consumer slot.
    correlation = next(c for c in result.correlations if c.variable == "orderId")
    for index in correlation.consumers:
        request = result.capture.requests[index].request
        request.path = request.path.replace(correlation.value, "literal")
    path, _, reports = emit_jmx(result, tmp_path)
    summary = build_web_summary(result, "probe", {}, path.read_bytes())
    assert "orderId" in {m["field"] for m in summary["manualCorrelations"]}
    assert any("orderId" in p.read_text(encoding="utf-8") for p in reports)


def test_conversion_api_summary_matches_downloaded_jmx(tmp_path):
    import functools
    import http.client
    import json
    import threading
    from http.server import ThreadingHTTPServer
    from unittest.mock import patch
    from har2jmx.paths import ROOT
    from har2jmx.server.handler import AppHandler

    server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(AppHandler, directory=str(ROOT)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
    body = b'--probe\r\nContent-Disposition: form-data; name="harfile"; filename="probe.har"\r\n\r\n{}\r\n--probe--\r\n'
    try:
        with patch("har2jmx.server.handler.OUTPUT_DIR", tmp_path), patch("har2jmx.server.handler.analyze", return_value=encoded_result()):
            connection.request("POST", "/api/convert", body=body,
                               headers={"Content-Type": "multipart/form-data; boundary=probe"})
            response = connection.getresponse()
            assert response.status == 200
            summary = json.loads(response.read())
            connection.request("GET", "/download/" + summary["downloads"]["jmx"])
            response = connection.getresponse()
            assert response.status == 200
            root = ET.fromstring(response.read())
            for name in ["SAMLRequest", "SAMLResponse"]:
                assert arg_values(root, name) == ["${" + name + "}"]
                assert summary["correlationImplementation"][name]["implemented"]
    finally:
        connection.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
