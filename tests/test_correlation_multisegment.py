"""Multi-segment path values: one logical id that legitimately contains "/".

A DOI (10.1002/9781119584414.ch4) or an org/repo id (sentence-transformers/all-MiniLM-L6-v2) spans
several URL segments, so no single-segment slot and no root-anchored prefix can ever equal it.

Matching is SEGMENT-AWARE, never substring: a value is only recognised as a contiguous run of WHOLE
"/" segments, and the same canonical representation is used for discovery and for substitution. The
collision tests below are the point of the exercise — a value that merely shares text with the path,
or that lines up only mid-segment, must NOT be substituted.
"""
from __future__ import annotations

import json
import re

from har2jmx.emit import build_jmx_xml, validate_plan
from har2jmx.engine import analyze
from har2jmx.validate import MaterializationStatus, audit_materialization


def _post(url, resp, *, sec=0, body=None):
    return {"startedDateTime": f"2024-01-01T10:00:{sec:02d}.000Z", "time": 30,
            "request": {"method": "POST", "url": url, "cookies": [], "queryString": [],
                        "headers": [{"name": "Content-Type", "value": "application/json"}],
                        "postData": {"mimeType": "application/json",
                                     "text": json.dumps(body or {"n": "a"})}},
            "response": {"status": 201,
                         "headers": [{"name": "Content-Type", "value": "application/json"}],
                         "cookies": [], "content": {"mimeType": "application/json", "text": resp}}}


def _get(url, *, sec=1, resp="{}"):
    return {"startedDateTime": f"2024-01-01T10:00:{sec:02d}.000Z", "time": 30,
            "request": {"method": "GET", "url": url, "cookies": [], "queryString": [], "headers": []},
            "response": {"status": 200,
                         "headers": [{"name": "Content-Type", "value": "application/json"}],
                         "cookies": [], "content": {"mimeType": "application/json", "text": resp}}}


def _run(entries):
    res = analyze(json.dumps({"log": {"version": "1.2", "entries": entries}}).encode())
    return res, build_jmx_xml(res).decode()


def _paths(xml):
    return re.findall(r'HTTPSampler\.path">([^<]*)<', xml)


def _assert_span_correlated(res, xml, value, expected_path):
    dec = [c for c in res.correlations if str(c.value) == value]
    assert dec, f"{value!r} was not correlated"
    d = dec[0]
    ok = {c.value for c in res.extractor_checks if c.ok}
    assert value in ok, f"{value!r} extractor did not verify"
    assert expected_path in _paths(xml), f"expected {expected_path} in {_paths(xml)}"
    assert value not in xml, f"{value!r} still hardcoded"
    checks = [c for c in audit_materialization(res, xml) if c.variable == d.variable]
    assert checks and checks[0].status in (MaterializationStatus.MATERIALIZED,
                                           MaterializationStatus.SUPERSEDED), checks[0].diagnostic()
    assert validate_plan(res, xml) == []
    return d


def test_doi_style_multi_segment_value():
    res, xml = _run([
        _post("https://x.io/api/register", json.dumps({"ref": "10.1002/9781119584414.ch4"})),
        _get("https://x.io/works/10.1002/9781119584414.ch4"),
    ])
    d = _assert_span_correlated(res, xml, "10.1002/9781119584414.ch4", "/works/${%s}" % "ref")
    assert d.variable == "ref"


def test_org_repo_style_value():
    res, xml = _run([
        _post("https://x.io/api/register", json.dumps({"repoId": "acme-corp/widget-service"})),
        _get("https://x.io/api/models/acme-corp/widget-service"),
    ])
    _assert_span_correlated(res, xml, "acme-corp/widget-service", "/api/models/${repoId}")


def test_multi_segment_value_with_trailing_subresource():
    """The surrounding URL structure after the span must be preserved."""
    res, xml = _run([
        _post("https://x.io/api/register", json.dumps({"repoId": "acme-corp/widget-service"})),
        _get("https://x.io/api/models/acme-corp/widget-service/files"),
    ])
    _assert_span_correlated(res, xml, "acme-corp/widget-service",
                            "/api/models/${repoId}/files")


def test_deeply_nested_multi_segment_identifier():
    res, xml = _run([
        _post("https://x.io/api/register", json.dumps({"nodePath": "eu/west/zone-7/node-42"})),
        _get("https://x.io/v2/topology/eu/west/zone-7/node-42/status"),
    ])
    _assert_span_correlated(res, xml, "eu/west/zone-7/node-42",
                            "/v2/topology/${nodePath}/status")


def test_normal_single_segment_identifier_still_works():
    res, xml = _run([
        _post("https://x.io/api/register", json.dumps({"ref": "TKNa1b2c3d4e5"})),
        _get("https://x.io/api/items/TKNa1b2c3d4e5"),
    ])
    _assert_span_correlated(res, xml, "TKNa1b2c3d4e5", "/api/items/${ref}")


# ---- collision cases: these must NOT be substituted -----------------------------------------------

def test_similar_but_not_equal_path_is_not_substituted():
    """A path that shares the first segment of the value but not the whole span."""
    res, xml = _run([
        _post("https://x.io/api/register", json.dumps({"repoId": "acme-corp/widget-service"})),
        _get("https://x.io/api/models/acme-corp/other-service"),
    ])
    assert all(str(c.value) != "acme-corp/widget-service" for c in res.correlations), \
        "a partially-overlapping path must not produce a correlation"
    assert "/api/models/acme-corp/other-service" in _paths(xml)


def test_mid_segment_prefix_collision_is_not_substituted():
    """The value lines up only INSIDE a segment ("widget-service" vs "widget-service-v2")."""
    res, xml = _run([
        _post("https://x.io/api/register", json.dumps({"repoId": "acme-corp/widget-service"})),
        _get("https://x.io/api/models/acme-corp/widget-service-v2"),
    ])
    assert "/api/models/acme-corp/widget-service-v2" in _paths(xml), \
        "a mid-segment prefix must never be replaced — that would be substring matching"
    assert "${repoId}" not in xml


def test_suffix_collision_is_not_substituted():
    """The value appears as a suffix of a longer segment, not as whole segments."""
    res, xml = _run([
        _post("https://x.io/api/register", json.dumps({"ref": "10.1002/9781119584414.ch4"})),
        _get("https://x.io/works/prefix10.1002/9781119584414.ch4"),
    ])
    assert "/works/prefix10.1002/9781119584414.ch4" in _paths(xml)


def test_value_not_consumed_anywhere_is_not_correlated():
    res, _ = _run([
        _post("https://x.io/api/register", json.dumps({"repoId": "acme-corp/widget-service"})),
        _get("https://x.io/api/unrelated"),
    ])
    assert all(str(c.value) != "acme-corp/widget-service" for c in res.correlations)


def test_sibling_segment_field_does_not_produce_a_redundant_extractor():
    """When a sibling field equals one segment of a longer correlated span, the longer span wins and
    the sibling must NOT ship its own (unreferenced) extractor."""
    res, xml = _run([
        _post("https://x.io/api/register",
              json.dumps({"owner": "acme-corp", "repoId": "acme-corp/widget-service"})),
        _get("https://x.io/api/models/acme-corp/widget-service"),
    ])
    assert "/api/models/${repoId}" in _paths(xml)
    refs = set(re.findall(r'RegexExtractor\.refname">([^<]+)<', xml))
    refs |= set(re.findall(r'referenceNames">([^<]+)<', xml))
    assert "owner" not in refs, "a span already covered by a longer variable must not get its own extractor"
    assert validate_plan(res, xml) == [], "no MATERIALIZATION_FAILED for a superseded span"
