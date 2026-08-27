"""Milestone 1 tests — normalized IR builder.

Runs under pytest, and also directly:  PYTHONPATH=src python tests/test_ir_build.py
"""
from __future__ import annotations

from pathlib import Path

from har2jmx.ir.build import build_capture
from har2jmx.ir.normalized import BodyKind, NormalizedCapture

FIXTURE = Path(__file__).parent / "fixtures" / "sample_mini.har"


def _capture() -> NormalizedCapture:
    return build_capture(FIXTURE.read_bytes())


def test_capture_keeps_every_entry():
    cap = _capture()
    # IR keeps everything (static + telemetry included); nothing filtered at this stage.
    assert cap.count == 6
    assert cap.total_har_entries == 6
    assert cap.pages.get("page_2") == "Ward Dashboard"
    # sequence is contiguous and 0-based
    assert [r.index for r in cap.requests] == [0, 1, 2, 3, 4, 5]


def test_json_request_and_response_and_setcookie():
    r = _capture().requests[0]
    assert r.method == "POST"
    assert r.request.body.kind == BodyKind.JSON
    assert r.request.body.json["username"] == "nurse01"
    assert r.response.body.kind == BodyKind.JSON
    assert r.response.body.json["userId"] == 42
    assert ("SESSIONID", "abc123def456") in r.response.set_cookies


def test_query_parsing_and_json_list_response():
    r = _capture().requests[1]
    assert ("ward", "3") in r.request.query
    assert ("status", "active") in r.request.query
    assert r.response.body.kind == BodyKind.JSON
    assert isinstance(r.response.body.json, list)
    assert r.response.body.json[0]["patientId"] == 1001


def test_static_asset_path_segments_and_mime():
    r = _capture().requests[2]
    assert r.request.path_segments == ["assets", "logo.svg"]
    assert "svg" in r.response.mime


def test_form_body_detected():
    r = _capture().requests[3]
    assert r.request.body.kind == BodyKind.FORM
    assert ("mob_dl", "5000") in r.request.body.form
    assert r.status == 204


def test_graphql_operation_detected():
    r = _capture().requests[4]
    assert r.request.body.kind == BodyKind.GRAPHQL
    assert r.request.body.graphql_operation == "GetDoctor"


def test_redirect_location_captured():
    r = _capture().requests[5]
    assert str(r.status) == "302"
    assert r.response.redirect_location.endswith("code=AUTHCODE")
    assert ("state", "xyzstate") in r.request.query


def test_context_fields():
    r = _capture().requests[0]
    assert r.context.pageref == "page_1"
    assert r.context.time_ms == 320
    assert r.context.referer.endswith("/login")


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for fn in fns:
        try:
            fn()
        except AssertionError as e:
            print(f"FAIL  {fn.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            print(f"ERROR {fn.__name__}: {type(e).__name__}: {e}")
        else:
            passed += 1
            print(f"ok    {fn.__name__}")
    print(f"\n{passed}/{len(fns)} passed")
    raise SystemExit(0 if passed == len(fns) else 1)
