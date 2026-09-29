"""Candidate discovery: whole client-originated slots reach intent; substitution is slot-aware."""
from __future__ import annotations

import json
import re

from har2jmx.emit import build_jmx_xml
from har2jmx.engine import analyze
from har2jmx.parameterize import ParameterIntent

_UDV = {"THREADS", "LOOPS", "RAMP", "THINKTIME", "BASE_URL", "PROTOCOL", "HOLD", "DURATION", "TIMEOUT"}


def _e(method, url, status=200, resp="{}", body=None, form=None, headers=None, ts="2026-01-01T10:00:00.000Z"):
    req_h = [{"name": "Accept", "value": "application/json"}]
    for k, v in (headers or {}).items():
        req_h.append({"name": k, "value": v})
    e = {
        "startedDateTime": ts, "time": 20,
        "request": {"method": method, "url": url, "headers": req_h, "cookies": []},
        "response": {
            "status": status,
            "headers": [{"name": "Content-Type", "value": "application/json"}],
            "content": {"mimeType": "application/json", "text": resp},
        },
    }
    if body is not None:
        e["request"]["postData"] = {"mimeType": "application/json", "text": body}
        e["request"]["headers"].append({"name": "Content-Type", "value": "application/json"})
    if form is not None:
        e["request"]["postData"] = {
            "mimeType": "application/x-www-form-urlencoded",
            "text": form,
        }
        e["request"]["headers"].append({"name": "Content-Type", "value": "application/x-www-form-urlencoded"})
    return e


def _har(entries):
    return json.dumps({"log": {"version": "1.2", "entries": entries}}).encode()


def _run(entries):
    res = analyze(_har(entries))
    xml = build_jmx_xml(res, {"threads": "5"}).decode()
    return res, xml


def _csv_values(res):
    return {v for d in res.parameterization.datasets for row in d.rows for v in row.values()}


def _csv_cols(xml):
    cols = []
    for names in re.findall(r'variableNames">([^<]+)<', xml):
        cols += [c.strip() for c in names.split(",") if c.strip()]
    return cols


def _vars(xml):
    return set(re.findall(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", xml)) - _UDV


def _arg_value(xml, name):
    m = re.search(
        rf'elementProp name="{re.escape(name)}"[^>]*>.*?Argument\.value">([^<]*)<',
        xml, re.S,
    )
    return m.group(1) if m else None


def test_path_only_business_input():
    res, xml = _run([_e("GET", "https://wiki.example/wiki/Albert_Einstein")])
    vals = _csv_values(res)
    assert "Albert_Einstein" in vals
    assert "wiki" not in vals
    assert "${" in xml and "Albert_Einstein" not in re.findall(r'HTTPSampler.path">([^<]+)<', xml)[0]


def test_query_only_business_input():
    res, xml = _run([_e("GET", "https://shop.example/search?q=computer")])
    assert "computer" in _csv_values(res)
    assert _arg_value(xml, "q") == "${q}"


def test_json_business_input():
    res, xml = _run([_e("POST", "https://api.example/checkout", body='{"sku":"SKU-44","qty":1}')])
    assert "SKU-44" in _csv_values(res)
    assert "${" in xml and "SKU-44" not in xml.split("HTTPSamplerProxy")[1][:2000]


def test_form_business_input():
    res, xml = _run([_e("POST", "https://pets.example/adopt", form="breed=labrador&count=2")])
    vals = _csv_values(res)
    assert "labrador" in vals
    assert "2" in vals
    assert _arg_value(xml, "breed") == "${breed}"
    assert _arg_value(xml, "count") == "${count}"


def test_short_numeric_query_slot_aware():
    res, xml = _run([
        _e("GET", "https://api.example/items?page=2&count=2&amount=100&year=2026&id=3"),
    ])
    vals = _csv_values(res)
    for v in ("2", "100", "2026", "3"):
        assert v in vals
    assert _arg_value(xml, "page") == "${page}"
    assert _arg_value(xml, "count") == "${count}"
    assert _arg_value(xml, "amount") == "${amount}"
    assert _arg_value(xml, "year") == "${year}"
    assert _arg_value(xml, "id") == "${id}"
    # no global replace: a different slot still holding literal 2 would be sort=asc, not page
    assert "replace(\"2\"" not in xml


def test_short_numeric_path_input():
    res, xml = _run([_e("GET", "https://shop.example/product/123")])
    assert "123" in _csv_values(res)
    path = re.findall(r'HTTPSampler.path">([^<]+)<', xml)[0]
    assert "${" in path and "123" not in path
    assert "product" not in _csv_values(res)


def test_search_term_country_name_barcode():
    res, _xml = _run([
        _e("GET", "https://x.example/find?q=harbour&country=India&barcode=5901234123457"),
    ])
    vals = _csv_values(res)
    assert "harbour" in vals
    assert "India" in vals
    assert "5901234123457" in vals


def test_logical_parameter_tuples():
    res, xml = _run([
        _e("GET", "https://maps.example/geo?lat=22.5726&lon=88.3639"),
        _e("GET", "https://pay.example/quote?amount=100&currency=USD", ts="2026-01-01T10:00:01.000Z"),
        _e("GET", "https://shop.example/filter?minPrice=10&maxPrice=50", ts="2026-01-01T10:00:02.000Z"),
    ])
    vals = _csv_values(res)
    for v in ("22.5726", "88.3639", "100", "USD", "10", "50"):
        assert v in vals
    assert _arg_value(xml, "lat") == "${lat}"
    assert _arg_value(xml, "lon") == "${lon}"


def test_list_detail_selected_entity_only():
    items = [{"productId": str(i), "name": f"P{i}"} for i in range(1, 101)]
    res, _xml = _run([
        _e("GET", "https://shop.example/products", resp=json.dumps({"products": items})),
        _e("GET", "https://shop.example/products/37", resp='{"productId":"37"}',
           ts="2026-01-01T10:00:02.000Z"),
    ])
    vals = _csv_values(res)
    assert "37" in vals
    assert "1" not in vals or len([r for d in res.parameterization.datasets for r in d.rows]) <= 2


def test_list_detail_unused_entities_not_dumped():
    res, _xml = _run([
        _e("GET", "https://shop.example/products",
           resp='{"products":[{"productId":"11"},{"productId":"22"},{"productId":"33"}]}'),
        _e("GET", "https://shop.example/products/22", resp="{}", ts="2026-01-01T10:00:02.000Z"),
    ])
    vals = _csv_values(res)
    assert "22" in vals
    assert "11" not in vals and "33" not in vals


def test_static_query_configuration_stays_literal():
    res, xml = _run([
        _e("GET", "https://app.example/api/items?language=en-US&sortOrder=asc&pageSize=20&q=laptop"),
    ])
    cols = set(_csv_cols(xml))
    assert "language" not in cols and "sortOrder" not in cols and "pageSize" not in cols
    assert "laptop" in _csv_values(res)
    assert _arg_value(xml, "language") == "en-US"
    assert _arg_value(xml, "q") == "${q}"


def test_runtime_correlation_candidate_not_csv():
    res, xml = _run([
        _e("POST", "https://app.example/orders", status=201,
           body='{"item":"book"}', resp='{"orderId":"ORD-556677"}'),
        _e("GET", "https://app.example/orders/ORD-556677",
           resp='{"orderId":"ORD-556677"}', ts="2026-01-01T10:00:02.000Z"),
    ])
    assert "ORD-556677" not in _csv_values(res)
    assert "JSONPostProcessor" in xml


def test_unknown_field_names_become_candidates():
    res, xml = _run([_e("POST", "https://n.example/rpc", body='{"zxqv":"harbour-port"}')])
    assert "harbour-port" in _csv_values(res)
    cols = [c for d in res.parameterization.datasets for c in d.columns]
    chosen = next(c for c in cols if "harbour-port" in {c.sample, c.original, c.normalized})
    assert chosen.intent == ParameterIntent.USER_INPUT.value
    assert "${zxqv}" in xml or _arg_value(xml, "zxqv") is None  # json body


def test_unfamiliar_domain_path_and_query():
    res, _xml = _run([
        _e("GET", "https://n.example/widgets/W-4400?flux=amber"),
    ])
    vals = _csv_values(res)
    assert "W-4400" in vals
    assert "amber" in vals


def test_opaque_unknown_is_review_not_csv():
    res, _xml = _run([_e("POST", "https://app.example/rpc", body='{"nonceBlob":"zz9yy8xx7ww6vv"}')])
    assert "zz9yy8xx7ww6vv" not in _csv_values(res)


def test_slot_aware_does_not_global_replace_short_numeric():
    res, xml = _run([
        _e("GET", "https://api.example/catalog?page=2"),
        _e("GET", "https://api.example/catalog?sortOrder=asc&n=2", ts="2026-01-01T10:00:02.000Z"),
    ])
    assert "2" in _csv_values(res)
    # second request: n=2 is a slot; sortOrder stays literal asc — and the path/query
    # must not become ${page} on a request that has no page parameter.
    assert xml.count("${page}") >= 1
    assert _arg_value(xml, "sortOrder") == "asc"
    # the second sampler's n slot is its own column if parameterized, not a blanket ${page}
    n_val = _arg_value(xml, "n")
    assert n_val != "${page}"
    assert n_val in {"${n}", "2"}


def test_short_numeric_json_body():
    res, xml = _run([_e("POST", "https://api.example/cart", body='{"qty":3,"sku":"SKU-9"}')])
    assert "3" in _csv_values(res)
    assert "${qty}" in xml or '"${qty}"' in xml


def test_package_style_path_value():
    res, xml = _run([_e("GET", "https://registry.example/package/performance-results-parser")])
    assert "performance-results-parser" in _csv_values(res)
    path = re.findall(r'HTTPSampler.path">([^<]+)<', xml)[0]
    assert "performance-results-parser" not in path


def test_static_api_version_query():
    _res, xml = _run([
        _e("GET", "https://api.example/items?api-version=2024-01-01&q=laptop"),
    ])
    assert _arg_value(xml, "q") == "${q}"
    assert _arg_value(xml, "api-version") in {"2024-01-01", None} or "api-version" not in _csv_cols(xml)


def test_pagination_configuration_hardcoded():
    _res, xml = _run([
        _e("GET", "https://api.example/users?nat=gb&results=3"),
    ])
    cols = set(_csv_cols(xml))
    assert "results" not in cols
    assert _arg_value(xml, "results") == "3"


def test_origin_destination_tuple():
    res, xml = _run([
        _e("GET", "https://maps.example/route?origin=DEL&destination=BOM"),
    ])
    vals = _csv_values(res)
    assert "DEL" in vals and "BOM" in vals
    assert _arg_value(xml, "origin") == "${origin}"
    assert _arg_value(xml, "destination") == "${destination}"


def test_duplicate_page_not_two_csv_columns():
    res, xml = _run([
        _e("GET", "https://reqres.example/api/users?page=2",
           resp='{"page":2,"data":[{"id":7,"email":"a@b.c"},{"id":8,"email":"d@e.f"}]}'),
        _e("GET", "https://reqres.example/api/users/7", resp='{"id":7}', ts="2026-01-01T10:00:02.000Z"),
    ])
    cols = _csv_cols(xml)
    assert cols.count("page") <= 1


def test_observe_then_use_ip_is_correlated_not_csv():
    res, xml = _run([
        _e("GET", "https://api.ipify.org/?format=json", resp='{"ip":"203.0.113.9"}'),
        _e("GET", "https://ipapi.example/json/203.0.113.9",
           resp='{"query":"203.0.113.9"}', ts="2026-01-01T10:00:02.000Z"),
    ])
    assert "203.0.113.9" not in _csv_values(res)
    assert "JSONPostProcessor" in xml


def test_selected_guid_from_list_is_csv_not_correlation():
    res, _xml = _run([
        _e("GET", "https://brew.example/v1/breweries?by_city=x",
           resp='[{"id":"aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee","name":"A"},'
                '{"id":"11111111-2222-3333-4444-555555555555","name":"B"}]'),
        _e("GET", "https://brew.example/v1/breweries/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
           resp='{"id":"aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"}', ts="2026-01-01T10:00:02.000Z"),
    ])
    assert "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee" in _csv_values(res)
    assert not any(c.value == "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee" for c in res.correlations)


def test_path_file_stem_is_parameterized():
    res, xml = _run([_e("GET", "https://off.example/api/v2/product/737628064502.json")])
    assert "737628064502" in _csv_values(res)
    path = re.findall(r'HTTPSampler.path">([^<]+)<', xml)[0]
    assert "737628064502" not in path or "${" in path


def test_country_path_selector_with_numeric_identity():
    res, xml = _run([_e("GET", "https://zip.example/us/90210")])
    vals = _csv_values(res)
    assert "90210" in vals
    assert "us" in vals


def test_static_configuration_intent_not_csv():
    res, xml = _run([
        _e("GET", "https://app.example/api/items?sortOrder=desc&q=laptop"),
    ])
    assert "desc" not in _csv_values(res)
    assert _arg_value(xml, "sortOrder") == "desc"


def test_candidate_without_jmx_consumer_has_no_csv_column():
    from har2jmx.emit import build_jmx_xml
    res, xml = _run([
        _e("GET", "https://app.example/hidden", resp='{"unusedCatalog":"ZZ-9999"}'),
        _e("GET", "https://app.example/home", resp='{"ok":true}', ts="2026-01-01T10:00:02.000Z"),
    ])
    cols = _csv_cols(xml)
    refs = _vars(xml)
    assert set(cols) <= refs

