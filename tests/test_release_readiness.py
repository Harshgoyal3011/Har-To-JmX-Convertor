"""Part 16-18 — product readiness: input safety, security/data-safety, and large-HAR performance.

Every check runs the real engine. The converter must fail SAFELY (clean ValueError or a valid, possibly
empty, plan) rather than crash or emit corrupted JMX.
"""
from __future__ import annotations

import json
import time
from xml.dom import minidom

import pytest

from har2jmx.emit import build_jmx_xml, emit_jmx
from har2jmx.engine import analyze
from har2jmx.webreport import build_web_summary


def _har(entries, **log):
    d = {"log": {"version": "1.2", "entries": entries, **log}}
    return json.dumps(d).encode()


def _well_formed(xml: bytes):
    minidom.parseString(xml)          # raises if not well-formed
    return True


# ============================ Part 16 — input safety ============================

@pytest.mark.parametrize("bad", [
    b"",                                   # empty upload
    b"not json at all",                    # malformed
    b"{}",                                 # no log
    b'{"log": {}}',                        # no entries
    b'{"log": {"entries": "nope"}}',       # entries not a list
])
def test_malformed_har_raises_clean_valueerror(bad):
    with pytest.raises(ValueError):
        analyze(bad)


def test_empty_but_valid_har_produces_well_formed_plan():
    xml = build_jmx_xml(analyze(_har([])))
    assert _well_formed(xml)               # empty capture -> valid (empty) plan, no crash


def test_missing_response_bodies_and_fields():
    entries = [{"startedDateTime": "2024-01-01T10:00:00.000Z", "time": 10,
                "request": {"method": "GET", "url": "https://app.example.com/api/x", "headers": [], "cookies": []},
                "response": {"status": 200, "headers": [], "content": {}}}]
    assert _well_formed(build_jmx_xml(analyze(_har(entries))))


def test_malformed_url_does_not_crash():
    entries = [{"startedDateTime": "2024-01-01T10:00:00.000Z", "time": 10,
                "request": {"method": "GET", "url": "::://not a url", "headers": [], "cookies": []},
                "response": {"status": 200, "headers": [], "content": {"mimeType": "application/json", "text": "{}"}}}]
    assert _well_formed(build_jmx_xml(analyze(_har(entries))))


def test_unicode_and_encoded_values():
    entries = [{"startedDateTime": "2024-01-01T10:00:00.000Z", "time": 10,
                "request": {"method": "POST", "url": "https://app.example.com/api/users",
                            "headers": [{"name": "Content-Type", "value": "application/json"}], "cookies": [],
                            "postData": {"mimeType": "application/json",
                                         "text": json.dumps({"name": "José Müller 日本語", "city": "Zürich%20"})}},
                "response": {"status": 201, "headers": [{"name": "Content-Type", "value": "application/json"}],
                             "content": {"mimeType": "application/json", "text": '{"userId":"U-1"}'}}}]
    xml = build_jmx_xml(analyze(_har(entries)))
    assert _well_formed(xml)
    assert "UTF-8" in xml.decode()         # request charset pinned (no mojibake under load)


def test_http2_pseudo_headers_not_emitted():
    entries = [{"startedDateTime": "2024-01-01T10:00:00.000Z", "time": 10,
                "request": {"method": "GET", "url": "https://api.example.com/orders", "cookies": [], "headers": [
                    {"name": ":authority", "value": "api.example.com"}, {"name": ":method", "value": "GET"},
                    {"name": "sec-ch-ua", "value": "x"}, {"name": "Accept", "value": "application/json"}]},
                "response": {"status": 200, "headers": [{"name": "Content-Type", "value": "application/json"}],
                             "content": {"mimeType": "application/json", "text": "{}"}}}]
    xml = build_jmx_xml(analyze(_har(entries))).decode()
    assert ":authority" not in xml and "sec-ch-ua" not in xml


# ============================ Part 17 — security / data safety ============================

def test_web_summary_masks_token_and_secret_values():
    entries = [
        {"startedDateTime": "2024-01-01T10:00:00.000Z", "time": 10,
         "request": {"method": "POST", "url": "https://app.example.com/api/login",
                     "headers": [{"name": "Content-Type", "value": "application/json"}], "cookies": [],
                     "postData": {"mimeType": "application/json", "text": '{"user":"bob"}'}},
         "response": {"status": 200, "headers": [{"name": "Content-Type", "value": "application/json"}],
                      "content": {"mimeType": "application/json", "text": '{"access_token":"SECRET-TOKEN-abc123xyz789"}'}}},
        {"startedDateTime": "2024-01-01T10:00:02.000Z", "time": 10,
         "request": {"method": "GET", "url": "https://app.example.com/api/me",
                     "headers": [{"name": "Authorization", "value": "Bearer SECRET-TOKEN-abc123xyz789"}], "cookies": []},
         "response": {"status": 200, "headers": [{"name": "Content-Type", "value": "application/json"}],
                      "content": {"mimeType": "application/json", "text": '{"id":"U1"}'}}},
    ]
    res = analyze(_har(entries))
    payload = build_web_summary(res, "rid", {"jmx": "x", "zip": "x", "csvs": [], "reports": []})
    blob = json.dumps(payload)
    # the full secret token is not exposed verbatim in the UI summary (it is masked)
    assert "SECRET-TOKEN-abc123xyz789" not in blob
    # a correlation for it is still reported (masked)
    assert any("token" in str(c.get("variable", "")).lower() or "…" in str(c.get("value", ""))
               for c in payload["correlations"])


def test_unexpected_error_does_not_dump_request_bodies(capsys):
    # analyze on garbage raises ValueError with a generic, user-safe message (no body/stack echoed to user)
    try:
        analyze(b"garbage-not-har")
    except ValueError as ex:
        assert "not a valid HAR" in str(ex)
        assert "garbage-not-har" not in str(ex)


# ============================ Part 18 — large-HAR performance ============================

def test_large_har_converts_within_bound_and_sane_size(tmp_path):
    # ~2000-entry synthetic HAR (login + business calls + interleaved noise)
    entries = [{"startedDateTime": "2024-01-01T10:00:00.000Z", "time": 10,
                "request": {"method": "POST", "url": "https://app.example.com/api/login",
                            "headers": [{"name": "Content-Type", "value": "application/x-www-form-urlencoded"}], "cookies": [],
                            "postData": {"mimeType": "application/x-www-form-urlencoded",
                                         "text": "signInName=perfSuperuser%40mailinator.com&password=Aug%402026"}},
                "response": {"status": 200, "headers": [{"name": "Content-Type", "value": "application/json"}],
                             "content": {"mimeType": "application/json", "text": '{"access_token":"TKN-1"}'}}}]
    for i in range(2000):
        host = "app.example.com" if i % 5 else "www.google-analytics.com"
        url = f"https://{host}/api/item/{i}" if i % 5 else f"https://{host}/g/collect?i={i}"
        mime = "application/json" if i % 5 else "image/gif"
        entries.append({"startedDateTime": f"2024-01-01T10:{(i//60) % 60:02d}:{i % 60:02d}.000Z", "time": 8,
                        "request": {"method": "GET", "url": url,
                                    "headers": [{"name": "Authorization", "value": "Bearer TKN-1"}], "cookies": []},
                        "response": {"status": 200, "headers": [{"name": "Content-Type", "value": mime}],
                                     "content": {"mimeType": mime, "text": '{"ok":1}' if i % 5 else ""}}})
    data = _har(entries)
    t0 = time.time()
    res = analyze(data)
    jmx_path, csv_paths, _ = emit_jmx(res, tmp_path, {"threads": "10"}, name="big")
    elapsed = time.time() - t0
    assert elapsed < 60, f"large HAR took {elapsed:.1f}s (>60s bound)"
    assert _well_formed(jmx_path.read_bytes())
    # analytics noise excluded even at scale
    assert "google-analytics" not in jmx_path.read_bytes().decode()
    print(f"[perf] {len(entries)} entries -> {elapsed:.2f}s, jmx={jmx_path.stat().st_size} bytes")
