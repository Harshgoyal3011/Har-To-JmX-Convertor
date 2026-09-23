"""RC-2 — XML safety: JMX generation must never crash on XML-1.0-illegal control characters (real
captured ad/RTB/telemetry bodies carry them). XML-safe text is preserved exactly; only the illegal
control class is stripped. Uses the ACTUAL failing payload shape."""
from __future__ import annotations

import json
from xml.dom import minidom

import pytest

from har2jmx.emit import build_jmx_xml, emit_jmx
from har2jmx.engine import analyze

# the COMPLETE XML 1.0-illegal C0 control class (everything except tab/newline/CR)
ILLEGAL = "".join(chr(c) for c in list(range(0x00, 0x09)) + [0x0B, 0x0C] + list(range(0x0E, 0x20)))


def _har(entries):
    return json.dumps({"log": {"version": "1.2", "entries": entries}}).encode()


def _post(url, body):
    return {"startedDateTime": "2024-01-01T10:00:00.000Z", "time": 20,
            "request": {"method": "POST", "url": url, "cookies": [],
                        "headers": [{"name": "Content-Type", "value": "application/json"}],
                        "postData": {"mimeType": "application/json", "text": json.dumps(body)}},
            "response": {"status": 200, "headers": [{"name": "Content-Type", "value": "application/json"}],
                         "content": {"mimeType": "application/json", "text": '{"ok":true}'}}}


def test_full_illegal_control_class_in_business_body_does_not_crash():
    # a BUSINESS request (app's own domain) whose body carries the full illegal class must still produce
    # a valid, well-formed plan — the converter must not crash, and every illegal char must be gone.
    body = {"item": "widget", "note": f"before{ILLEGAL}after"}
    xml = build_jmx_xml(analyze(_har([_post("https://app.example.com/api/orders", body)])))
    minidom.parseString(xml)                       # well-formed — no ExpatError
    x = xml.decode("utf-8")
    for ch in ILLEGAL:
        assert ch not in x                         # every illegal char stripped


def test_illegal_chars_in_header_and_query_do_not_crash():
    ent = {"startedDateTime": "2024-01-01T10:00:00.000Z", "time": 20,
           "request": {"method": "GET", "url": f"https://app.example.com/api/x?q=a{ILLEGAL}b", "cookies": [],
                       "headers": [{"name": "X-Custom", "value": f"h{ILLEGAL}v"},
                                   {"name": "Accept", "value": "application/json"}]},
           "response": {"status": 200, "headers": [{"name": "Content-Type", "value": "application/json"}],
                        "content": {"mimeType": "application/json", "text": "{}"}}}
    xml = build_jmx_xml(analyze(_har([ent])))
    minidom.parseString(xml)                        # no crash, well-formed


def test_xml_safe_text_is_preserved_byte_for_byte(tmp_path):
    # unicode / punctuation must be untouched (only the illegal control class is removed); the value may
    # land as a ${var} in the JMX or as data in the CSV — check both.
    body = {"searchTerm": "José Müller 日本語", "item": "widget"}
    res = analyze(_har([_post("https://app.example.com/api/search", body)]))
    jmx_path, csv_paths, _ = emit_jmx(res, tmp_path, {"threads": "5"}, name="uni")
    minidom.parseString(jmx_path.read_bytes())
    blob = jmx_path.read_bytes().decode("utf-8") + "".join(p.read_text(encoding="utf-8") for p in csv_paths)
    for token in ("José", "Müller", "日本語"):
        assert token in blob


def test_emit_jmx_writes_valid_files_with_illegal_payload(tmp_path):
    body = {"item": "x", "blob": ILLEGAL}
    res = analyze(_har([_post("https://app.example.com/api/orders", body)]))
    jmx_path, _csv, _rep = emit_jmx(res, tmp_path, {"threads": "5"}, name="safe")
    minidom.parseString(jmx_path.read_bytes())      # written file is well-formed
