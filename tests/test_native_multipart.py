"""Native multipart HAR normalization; no downstream decision rules involved."""
from __future__ import annotations

import base64

import pytest

from har2jmx.har.reader import post_files, post_pairs
from har2jmx.ir.build import build_capture
from har2jmx.ir.normalized import BodyKind


def _entry(parts: list[tuple[str, str]], *, params=None, boundary="captured-boundary", close=True):
    text = "".join(f"--{boundary}\r\n{headers}\r\n\r\n{value}\r\n" for headers, value in parts)
    if close:
        text += f"--{boundary}--\r\n"
    post = {"mimeType": f'multipart/form-data; boundary="{boundary}"', "text": text, "params": params or []}
    return {"request": {"method": "POST", "url": "https://example.test/submit", "postData": post},
            "response": {"status": 200, "content": {"mimeType": "text/plain", "text": "OK"}}}


def _field(name, value):
    return f'Content-Disposition: form-data; name="{name}"', value


def test_native_text_only_populates_ir_and_preserves_raw_boundary_and_values():
    entry = _entry([_field("title", "  résumé\r\nsecond line  "), _field("enabled", "false")])
    body = build_capture({"log": {"entries": [entry]}}).requests[0].request.body
    assert body.kind == BodyKind.MULTIPART
    assert body.form == [("title", "  résumé\r\nsecond line  "), ("enabled", "false")]
    assert body.raw == entry["request"]["postData"]["text"]
    assert body.mime == entry["request"]["postData"]["mimeType"]
    assert body.files == []


def test_text_and_file_retains_metadata_without_treating_file_bytes_as_inputs():
    entry = _entry([_field("description", "user text"),
                    (('Content-Disposition: form-data; name="upload"; filename="report.csv"\r\n'
                      'Content-Type: text/csv; charset=utf-8'), "id,name\r\n1,Ada")])
    assert post_pairs(entry)[0] == [("description", "user text")]
    assert post_files(entry) == [("upload", "report.csv", "text/csv; charset=utf-8")]
    body = build_capture({"log": {"entries": [entry]}}).requests[0].request.body
    assert body.files == post_files(entry)


def test_empty_filename_is_a_file_part_and_empty_text_remains_a_field():
    entry = _entry([_field("optional", ""),
                    (('Content-Disposition: form-data; name="upload"; filename=""\r\n'
                      'Content-Type: application/octet-stream'), "")])
    assert post_pairs(entry)[0] == [("optional", "")]
    # IR.files is an upload-path list: an empty path cannot be emitted safely.
    # Retain the empty file part in raw text without inventing a text field/file.
    assert post_files(entry) == []
    body = build_capture({"log": {"entries": [entry]}}).requests[0].request.body
    assert body.raw == entry["request"]["postData"]["text"]
    assert 'filename=""' in body.raw


def test_repeated_names_preserve_order_and_different_values_including_empty():
    entry = _entry([_field("items[]", "first"), _field("items[]", ""), _field("items[]", "second")])
    assert post_pairs(entry)[0] == [("items[]", "first"), ("items[]", ""), ("items[]", "second")]


def test_quoted_disposition_parameters_and_literal_quotes():
    entry = _entry([(r'Content-Disposition: form-data; name="notes;detail"', '"quoted"; value'),
                    (r'Content-Disposition: form-data; name="upload"; filename="a;\"b.txt"', "file")])
    assert post_pairs(entry)[0] == [("notes;detail", '"quoted"; value')]
    assert post_files(entry) == [("upload", 'a;"b.txt', "application/octet-stream")]


def test_quoted_filename_and_name_preserve_internal_leading_and_trailing_spaces():
    entry = _entry([('Content-Disposition: form-data; name=" upload "; filename=" a.txt "', "file")])
    assert post_files(entry) == [(" upload ", " a.txt ", "application/octet-stream")]


@pytest.mark.parametrize("charset,value", [("utf-8", "東京"), ("iso-8859-1", "café")])
def test_declared_charset_does_not_reencode_already_decoded_har_text(charset, value):
    entry = _entry([((f'Content-Disposition: form-data; name="label"\r\n'
                      f'Content-Type: text/plain; charset={charset}'), value)])
    assert post_pairs(entry)[0] == [("label", value)]


def test_transfer_encoded_text_uses_declared_charset():
    encoded = base64.b64encode("café".encode("iso-8859-1")).decode("ascii")
    entry = _entry([(('Content-Disposition: form-data; name="label"\r\n'
                      'Content-Type: text/plain; charset=iso-8859-1\r\n'
                      'Content-Transfer-Encoding: base64'), encoded)])
    assert post_pairs(entry)[0] == [("label", "café")]


def test_populated_params_remain_authoritative_even_when_only_files_exist():
    params = [{"name": "chosen", "value": "from params"},
              {"name": "upload", "fileName": "known.txt", "contentType": "text/plain"}]
    entry = _entry([_field("chosen", "raw differs"), _field("unexpected", "not added")], params=params)
    assert post_pairs(entry)[0] == [("chosen", "from params")]
    assert post_files(entry) == [("upload", "known.txt", "text/plain")]
    entry["request"]["postData"]["params"] = params[1:]
    assert post_pairs(entry)[0] == []
    assert post_files(entry) == [("upload", "known.txt", "text/plain")]


@pytest.mark.parametrize("case", ["missing-boundary", "incomplete", "bad-disposition", "missing-name"])
def test_malformed_or_incomplete_multipart_keeps_raw_and_does_not_crash(case):
    entry = _entry([_field("name", "value")], close=case != "incomplete")
    post = entry["request"]["postData"]
    if case == "missing-boundary":
        post["mimeType"] = "multipart/form-data"
    elif case == "bad-disposition":
        post["text"] = post["text"].replace("form-data; name", "attachment; name")
    elif case == "missing-name":
        post["text"] = post["text"].replace('; name="name"', "")
    body = build_capture({"log": {"entries": [entry]}}).requests[0].request.body
    assert body.form == []
    assert body.files == []
    assert body.raw == post["text"]


def test_embedded_json_and_security_fields_remain_exact_text_values():
    text = '{"count":2,"enabled":false,"ids":[1,2]}'
    token = "issued:opaque-security-token,123456"
    entry = _entry([('Content-Disposition: form-data; name="payload"\r\nContent-Type: application/json', text),
                    _field("_csrf", token), _field("_csrf", "second-issued-token")])
    body = build_capture({"log": {"entries": [entry]}}).requests[0].request.body
    assert body.form == [("payload", text), ("_csrf", token), ("_csrf", "second-issued-token")]
    assert body.json is None


def test_non_form_mime_is_not_parsed_as_multipart():
    entry = _entry([_field("name", "value")])
    entry["request"]["postData"]["mimeType"] = "text/plain"
    assert post_pairs(entry)[0] == []
    assert post_files(entry) == []
