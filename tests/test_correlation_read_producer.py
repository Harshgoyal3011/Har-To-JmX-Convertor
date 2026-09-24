"""Correlation recall for READ/search producers and for path / absolute-URL reuse.

Derived from the real-world benchmark (benchmark/BASELINE_REPORT.md), where every one of these shapes
was missed and the script shipped a hardcoded server value.

Policy encoded here (the entity-identifier carve-out):
  * a value the SERVER returned that a LATER request depends on is CORRELATED, whatever the producer's
    HTTP method — the search -> detail journey is the commonest real business flow there is;
  * EXCEPT catalog/master data, which stays a CSV parameter so load spreads across the catalog:
    an identifier of a discovered multi-instance entity, or a structured PREFIX-CODE id (PROD-4400).
"""
from __future__ import annotations

import json
import re

from har2jmx.emit import build_jmx_xml, validate_plan
from har2jmx.engine import analyze


def _e(method, url, *, resp="{}", sec=0, body=None, status=200):
    ent = {"startedDateTime": f"2024-01-01T10:00:{sec:02d}.000Z", "time": 30,
           "request": {"method": method, "url": url, "cookies": [], "queryString": [],
                       "headers": [{"name": "Content-Type", "value": "application/json"}]},
           "response": {"status": status, "headers": [{"name": "Content-Type", "value": "application/json"}],
                        "cookies": [], "content": {"mimeType": "application/json", "text": resp}}}
    if body is not None:
        ent["request"]["postData"] = {"mimeType": "application/json", "text": json.dumps(body)}
    return ent


def _run(entries):
    res = analyze(json.dumps({"log": {"version": "1.2", "entries": entries}}).encode())
    return res, build_jmx_xml(res).decode()


def _assert_correlated(res, xml, value):
    """decision -> verified extractor -> variable -> consumer substitution -> literal gone."""
    ok = {c.value for c in res.extractor_checks if c.ok}
    dec = [c for c in res.correlations if c.value == value]
    assert dec, f"{value!r} was not correlated"
    d = dec[0]
    assert d.consumers, f"{value!r} correlated with no downstream consumer"
    assert value in ok, f"{value!r} extractor did not verify (would be NOT_FOUND at run time)"
    refs = set(re.findall(r'RegexExtractor.refname">([^<]+)<', xml))
    refs |= set(re.findall(r'referenceNames">([^<]+)<', xml))
    assert d.variable in refs, f"no extractor emitted for {d.variable}"
    assert ("${%s}" % d.variable) in xml, f"${{{d.variable}}} not used downstream"
    assert value not in xml, f"{value!r} still hardcoded in the JMX"
    assert validate_plan(res, xml) == []


def _cols(res):
    return [c.name for d in res.parameterization.datasets for c in d.columns]


# ---- the four shapes the benchmark proved were missed ---------------------------------------------

def test_numeric_id_from_search_reused_as_query_param():
    res, xml = _run([
        _e("GET", "https://w.example.com/api?action=search&q=perf",
           resp=json.dumps({"query": {"search": [{"title": "A", "pageid": 6615610},
                                                 {"title": "B", "pageid": 35920450}]}}), sec=0),
        _e("GET", "https://w.example.com/api?action=info&pageids=6615610", sec=2),
    ])
    _assert_correlated(res, xml, "6615610")


def test_string_id_from_search_reused_as_path_segment():
    res, xml = _run([
        _e("GET", "https://f.example.com/api/search?cat=cereal",
           resp=json.dumps({"products": [{"code": "3168930010265"}, {"code": "3229820160672"}]}), sec=0),
        _e("GET", "https://f.example.com/api/product/3168930010265", sec=2),
    ])
    _assert_correlated(res, xml, "3168930010265")


def test_composite_resource_path_reused_with_extension_and_subresource():
    # "/works/OL1904498W" -> "/works/OL1904498W.json" and "/works/OL1904498W/editions.json"
    res, xml = _run([
        _e("GET", "https://l.example.com/search.json?q=perf",
           resp=json.dumps({"docs": [{"key": "/works/OL1904498W"}, {"key": "/works/OL284009W"}]}), sec=0),
        _e("GET", "https://l.example.com/works/OL1904498W.json", sec=2),
        _e("GET", "https://l.example.com/works/OL1904498W/editions.json?limit=2", sec=3),
    ])
    _assert_correlated(res, xml, "/works/OL1904498W")
    d = [c for c in res.correlations if c.value == "/works/OL1904498W"][0]
    assert len(d.consumers) >= 2, "both downstream requests depend on the key"


def test_absolute_url_returned_then_requested_verbatim():
    res, xml = _run([
        _e("GET", "https://p.example.com/api/v2/pokemon?limit=2",
           resp=json.dumps({"results": [{"name": "bulbasaur", "url": "https://p.example.com/api/v2/pokemon/1/"},
                                        {"name": "ivysaur", "url": "https://p.example.com/api/v2/pokemon/2/"}]}),
           sec=0),
        _e("GET", "https://p.example.com/api/v2/pokemon/1/", resp=json.dumps({"id": 1}), sec=2),
    ])
    _assert_correlated(res, xml, "https://p.example.com/api/v2/pokemon/1/")


# ---- the guards that keep this from over-correlating ----------------------------------------------

def test_structured_catalog_code_stays_a_parameter():
    # a PREFIX-CODE catalog id must stay CSV test data so load spreads across the catalog
    res, xml = _run([
        _e("GET", "https://s.example.com/api/products?cat=tools",
           resp=json.dumps({"products": [{"sku": "PROD-4400"}, {"sku": "PROD-4401"}]}), sec=0),
        _e("GET", "https://s.example.com/api/products/PROD-4400", sec=2),
    ])
    assert all(c.value != "PROD-4400" for c in res.correlations), \
        "a structured catalog code must not be correlated"
    assert "sku" in _cols(res)


def test_created_id_inside_a_list_is_not_correlated_by_match_one():
    # a POST-CREATED id sitting first in a list must NOT be resolved by "match #1": at replay the
    # first element may be a different record, so it stays unresolved and ships as a literal.
    res, xml = _run([
        _e("POST", "https://c.example.com/api/orders", body={"item": "x"}, status=201,
           resp=json.dumps({"orders": [{"orderId": "ORD-NEW-9"}, {"orderId": "ORD-OLD-1"}]}), sec=0),
        _e("GET", "https://c.example.com/api/orders/ORD-NEW-9", sec=2),
    ])
    ok = {c.value for c in res.extractor_checks if c.ok}
    assert "ORD-NEW-9" not in ok, "a created id inside a per-run list must not verify via match #1"


def test_value_returned_but_never_consumed_stays_master_data():
    # nothing downstream depends on it -> it remains selectable master data, not a correlation
    res, _ = _run([
        _e("GET", "https://n.example.com/api/items?q=a",
           resp=json.dumps({"items": [{"ref": "9988776655"}]}), sec=0),
        _e("GET", "https://n.example.com/api/unrelated", sec=2),
    ])
    assert all(c.value != "9988776655" for c in res.correlations)
