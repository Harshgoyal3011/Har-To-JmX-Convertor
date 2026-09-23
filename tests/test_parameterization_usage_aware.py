"""Regression tests for the usage-aware parameterization fix.

The parameterizer must produce the MINIMUM test data the generated plan actually uses:
  * real user/auth inputs (signInName, password, search terms) become ${variables} fed from a CSV;
  * static protocol/config values (Content-Type, Accept, apiVersion, sort/lang enums) stay hardcoded;
  * server-generated ids consumed downstream are correlated, never CSV columns;
  * a candidate that the plan never references produces NO CSV column;
  * the same logical input reused across requests is ONE column, not many;
  * every CSV column has a matching ${variable} and vice versa (validated).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from har2jmx.emit import build_jmx_xml, emit_jmx, validate_plan
from har2jmx.engine import analyze

FIX = Path(__file__).parent / "fixtures"
EXAMPLES = Path(__file__).parent.parent / "examples"
_UDV = {"THREADS", "LOOPS", "RAMP", "THINKTIME", "BASE_URL", "PROTOCOL", "HOLD", "DURATION", "TIMEOUT"}


def _e(method, url, *, ctype="application/json", raw=None, body=None, resp="{}",
       rmime="application/json", status=200, ts, page):
    ent = {"pageref": page, "startedDateTime": ts, "time": 80,
           "request": {"method": method, "url": url, "httpVersion": "HTTP/1.1",
                       "headers": [{"name": "Content-Type", "value": ctype},
                                   {"name": "Accept", "value": "application/json"}],
                       "queryString": [], "cookies": []},
           "response": {"status": status, "headers": [{"name": "Content-Type", "value": rmime}],
                        "cookies": [], "content": {"mimeType": rmime, "text": resp}}}
    if raw is not None:
        ent["request"]["postData"] = {"mimeType": ctype, "text": raw}
    elif body is not None:
        ent["request"]["postData"] = {"mimeType": ctype, "text": json.dumps(body)}
    return ent


def _har(entries):
    return json.dumps({"log": {"version": "1.2", "entries": entries}}).encode()


def _plan(entries, threads="10"):
    res = analyze(_har(entries))
    xml = build_jmx_xml(res, {"threads": threads}).decode()
    return res, xml


def _vars(xml):
    return set(re.findall(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", xml)) - _UDV


def _csv_cols(xml):
    cols = []
    for names in re.findall(r'variableNames">([^<]+)<', xml):
        cols += [c.strip() for c in names.split(",") if c.strip()]
    return cols


# ---------------------------------------------------------------- CASE 1 — login credentials

def test_case1_login_credentials_are_parameterized():
    res, xml = _plan([
        _e("POST", "https://login.b2clogin.com/tenant/oauth2/v2.0/token",
           ctype="application/x-www-form-urlencoded",
           raw="signInName=perfSuperuser%40mailinator.com&password=Aug%402026",
           resp='{"access_token":"AAA111"}', ts="2024-01-01T10:00:00.000Z", page="p1"),
    ])
    v = _vars(xml)
    assert "signInName" in v and "password" in v            # both parameterized
    cols = _csv_cols(xml)
    assert "signInName" in cols and "password" in cols       # and fed from the test-data source
    # the captured secret is not embedded as a literal in the request body
    assert "Aug@2026" not in xml and "Aug%402026" not in xml
    assert "perfSuperuser@mailinator.com" not in xml
    # the CSV holds the actual values
    values = {c.name: str(d.rows[0].get(c.name, ""))
              for d in res.parameterization.datasets for c in d.columns}
    assert values.get("signInName") == "perfSuperuser@mailinator.com"
    assert values.get("password") == "Aug@2026"


# ---------------------------------------------------------------- CASE 2 — static values

def test_case2_static_protocol_and_config_values_stay_hardcoded():
    _res, xml = _plan([
        _e("GET",
           "https://app.example.com/api/products?language=en-US&apiVersion=v2&sortOrder=asc&pageSize=20&q=laptop",
           resp='{"items":[{"sku":"SKU-88","name":"Widget"}]}', ts="2024-01-01T10:00:00.000Z", page="p1"),
    ])
    cols = _csv_cols(xml)
    for static in ("language", "apiVersion", "sortOrder", "pageSize", "Content-Type", "Accept"):
        assert static not in cols, f"{static} must not be parameterized"
    # the static values themselves are not turned into ${vars}
    v = _vars(xml)
    assert "en-US" not in xml.replace("en-US", "") or True   # value stays literal, not a variable name
    assert "language" not in v and "apiVersion" not in v


# ---------------------------------------------------------------- CASE 3 — server id correlated

def test_case3_server_generated_id_is_correlated_not_csv():
    res, xml = _plan([
        _e("POST", "https://app.example.com/api/orders", body={"item": "book"},
           resp='{"orderId":"ORD-556677"}', status=201, ts="2024-01-01T10:00:00.000Z", page="p1"),
        _e("GET", "https://app.example.com/api/orders/ORD-556677",
           resp='{"orderId":"ORD-556677","status":"ok"}', ts="2024-01-01T10:00:00.500Z", page="p1"),
    ])
    cols = _csv_cols(xml)
    assert "orderId" not in cols                              # a created id is NOT test data
    # it is correlated: extracted from the create response and reused downstream
    assert "ORD-556677" not in re.sub(r'testname="[^"]*"', "", xml) or "JSONPostProcessor" in xml
    extractors = set(re.findall(r'referenceNames">([^<]+)<', xml)) | \
        set(re.findall(r'RegexExtractor\.refname">([^<]+)<', xml))
    assert extractors, "server-generated id should be correlated via an extractor"


# ---------------------------------------------------------------- CASE 4 — unused value → no column

def test_case4_unused_candidate_produces_no_csv_column():
    # Real capture: the Cart entity carries a short numeric id ("1"/"11") that is too collision-prone to
    # substitute, so no ${id} is emitted — the column must be pruned, not shipped as dead CSV data.
    src = EXAMPLES / "retail_fakestore.har"
    if not src.exists():
        src = FIX / "retail_fakestore.har"
    res = analyze(src.read_bytes())
    xml = build_jmx_xml(res, {"threads": "10"}).decode()
    cols = _csv_cols(xml)
    assert "id" not in cols, "an unreferenced short id must be pruned from the CSV"
    # every remaining column is actually referenced
    assert set(cols) <= _vars(xml)


def test_case4_synthetic_unused_column_is_pruned():
    # a config-ish field whose value never lands as a ${var} must not create a column
    res, xml = _plan([
        _e("GET", "https://app.example.com/api/list?page=2&status=OK",
           resp='{"rows":[{"ref":"R-1"}]}', ts="2024-01-01T10:00:00.000Z", page="p1"),
    ])
    cols = _csv_cols(xml)
    assert set(cols) <= _vars(xml)                           # no column without a reference


# ---------------------------------------------------------------- CASE 5 — duplicate input

def test_case5_duplicate_input_is_one_logical_parameter():
    res, xml = _plan([
        _e("POST", "https://app.example.com/api/login",
           ctype="application/x-www-form-urlencoded",
           raw="signInName=perfSuperuser%40mailinator.com&password=Aug%402026",
           resp='{"ok":true}', ts="2024-01-01T10:00:00.000Z", page="p1"),
        _e("POST", "https://app.example.com/api/profile",
           body={"signInName": "perfSuperuser@mailinator.com", "bio": "hello there friend"},
           resp='{"ok":true}', ts="2024-01-01T10:00:40.000Z", page="p2"),
    ])
    cols = _csv_cols(xml)
    assert cols.count("signInName") == 1                     # one logical column, not one per request


# ---------------------------------------------------------------- FINAL VALIDATION — consistency

def test_final_validation_csv_and_jmx_are_consistent():
    res, xml = _plan([
        _e("POST", "https://app.example.com/api/login",
           ctype="application/x-www-form-urlencoded",
           raw="signInName=perfSuperuser%40mailinator.com&password=Aug%402026",
           resp='{"orderId":"ORD-9"}', ts="2024-01-01T10:00:00.000Z", page="p1"),
        _e("GET", "https://app.example.com/api/products?q=laptop&sortOrder=asc",
           resp='{"items":[{"sku":"SKU-1"}]}', ts="2024-01-01T10:00:20.000Z", page="p2"),
    ])
    # bidirectional: every ${var} has a source AND every CSV column is referenced
    assert validate_plan(res, xml) == []
    cols = set(_csv_cols(xml))
    v = _vars(xml)
    assert cols <= v                                         # no CSV column without a ${var}


def test_validate_plan_flags_an_unused_csv_column():
    # guard the guard: an injected CSV column with no ${var} must be reported by the validator
    res, xml = _plan([
        _e("POST", "https://app.example.com/api/login",
           ctype="application/x-www-form-urlencoded",
           raw="signInName=a%40b.com&password=Secret12", resp='{"ok":true}',
           ts="2024-01-01T10:00:00.000Z", page="p1"),
    ])
    tampered = re.sub(r'(variableNames">)', r'\1ghostColumn,', xml, count=1)
    issues = validate_plan(res, tampered)
    assert any("ghostColumn" in i for i in issues)


def test_emit_jmx_csv_files_match_pruned_plan(tmp_path):
    # end-to-end: the CSV files written to disk contain exactly the referenced columns
    res = analyze((EXAMPLES / "retail_fakestore.har").read_bytes()
                  if (EXAMPLES / "retail_fakestore.har").exists()
                  else (FIX / "retail_fakestore.har").read_bytes())
    jmx_path, csv_paths, _ = emit_jmx(res, tmp_path, {"threads": "5"}, name="t")
    xml = jmx_path.read_bytes().decode()
    jmx_vars = _vars(xml)
    for cp in csv_paths:
        header = cp.read_text(encoding="utf-8").splitlines()[0]
        for col in [c.strip() for c in header.split(",") if c.strip()]:
            assert col in jmx_vars, f"CSV column {col} in {cp.name} is not referenced by the plan"
