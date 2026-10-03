"""Lifecycle classification after discovery; fixtures are synthetic mechanics."""

import json
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from har2jmx.classify import ValueClass
from har2jmx.classify.lifecycle import graphql_operation_kind
from har2jmx.classify.value_engine import Lifecycle
from har2jmx.emit import build_jmx_xml, validate_plan
from har2jmx.engine import analyze


def exchange(query, response, variables=None, operation=None, *, index=0, path="/graphql", headers=()):
    payload = {"query": query, "variables": variables or {}}
    if operation:
        payload["operationName"] = operation
    return {
        "startedDateTime": f"2026-01-01T00:00:{index:02}.000Z",
        "time": 10,
        "request": {
            "method": "POST",
            "url": "https://lifecycle.example" + path,
            "headers": [{"name": n, "value": v} for n, v in headers],
            "postData": {"mimeType": "application/json", "text": json.dumps(payload)},
        },
        "response": {
            "status": 200,
            "headers": [],
            "content": {"mimeType": "application/json", "text": json.dumps(response)},
        },
    }


@pytest.mark.parametrize("value", ["AB", "XyZ123opaqueRef", "d288057d-9ac1-47f5-bba4-4a99a4b337ab", "76543"])
def test_query_read_selected_existing_record_ignores_identifier_shape(value):
    entries = [
        exchange(
            "query List { inventory { id display } }",
            {
                "data": {
                    "inventory": [{"id": value, "display": "First"}, {"id": "other", "display": "Second"}]
                }
            },
        ),
        exchange("query Detail($id: ID!) { record(id:$id) { id } }", {}, {"id": value}, index=1),
    ]
    result = analyze({"log": {"entries": entries}})
    verdict = result.classification.by_value(value)
    assert verdict.classification == ValueClass.BUSINESS_MASTER_DATA
    assert verdict.lifecycle == Lifecycle.EXISTING_BEFORE_RUN
    assert not any(c.value == value for c in result.correlations)
    xml = build_jmx_xml(result).decode()
    columns = [c for d in result.parameterization.datasets for c in d.columns]
    selected = next(c for c in columns if c.sample == value)
    assert "${" + selected.name + "}" in xml
    assert not ET.fromstring(xml).findall(".//JSONPostProcessor")


@pytest.mark.parametrize(
    "document, selected, expected",
    [
        ("query Browse { catalog { id } }", None, "query"),
        ("{ catalog { id } }", None, "query"),
        ("# mutation Fake { create { id } }\nquery Browse { catalog { id } }", None, "query"),
        ("fragment Values on Item { id } query Browse { catalog { ...Values } }", None, "query"),
        ('query Browse($filter: Filter = {text: "mutation"}) { catalog { id } }', None, "query"),
        ("query Read { catalog { id } } mutation Write { create { id } }", "Read", "query"),
        ("query Read { catalog { id } } mutation Write { create { id } }", "Write", "mutation"),
        ("query Read { catalog { id } } mutation Write { create { id } }", None, "unknown"),
        ("query Read { catalog { id } }", "Missing", "unknown"),
        ("subscription Events { events { id } }", None, "subscription"),
        ("query Read", None, "unknown"),
        ("query Read { catalog { id }", None, "unknown"),
        ("query Read { catalog { id } }}", None, "unknown"),
    ],
)
def test_operation_semantics_do_not_depend_on_transport_or_keyword_substrings(document, selected, expected):
    result = analyze({"log": {"entries": [exchange(document, {}, operation=selected)]}})
    assert graphql_operation_kind(result.capture.requests[0]) == expected


def test_creation_mutation_still_materializes_fresh_created_identity():
    value = "createdRecord123"
    entries = [
        exchange("mutation Create { createRecord { id } }", {"data": {"createRecord": {"id": value}}}),
        exchange("query Detail($id:ID!) { record(id:$id) { id } }", {}, {"id": value}, index=1),
    ]
    result = analyze({"log": {"entries": entries}})
    assert result.classification.by_value(value).lifecycle == Lifecycle.CREATED_THIS_RUN
    correlation = next(c for c in result.correlations if c.value == value)
    xml = build_jmx_xml(result).decode()
    assert value not in xml and "${" + correlation.variable + "}" in xml
    assert ET.fromstring(xml).find(".//JSONPostProcessor") is not None


def test_query_can_issue_auth_state_when_consumed_as_credential():
    value = "freshAccessState123"
    entries = [
        exchange("query Login { login { accessToken } }", {"data": {"login": {"accessToken": value}}}),
        exchange(
            "query Profile { profile { name } }", {}, index=1, headers=[("Authorization", "Bearer " + value)]
        ),
    ]
    result = analyze({"log": {"entries": entries}})
    assert result.classification.by_value(value).classification == ValueClass.RUNTIME_GENERATED
    correlation = next(c for c in result.correlations if c.value == value)
    xml = build_jmx_xml(result).decode()
    assert "Bearer ${" + correlation.variable + "}" in xml and value not in xml
    assert "Require fresh authentication state" in xml


def test_read_can_issue_refresh_state_consumed_in_token_exchange_body():
    value = "freshRefreshState123"
    entries = [
        exchange("query Login { login { refreshToken } }", {"data": {"login": {"refreshToken": value}}}),
        exchange(
            "mutation Refresh($refreshToken:String!) { refresh(refreshToken:$refreshToken) { accessToken } }",
            {}, {"refreshToken": value}, index=1,
        ),
    ]
    result = analyze({"log": {"entries": entries}})
    assert result.classification.by_value(value).classification == ValueClass.RUNTIME_GENERATED
    correlation = next(c for c in result.correlations if c.value == value)
    xml = build_jmx_xml(result).decode()
    assert value not in xml and "${" + correlation.variable + "}" in xml
    assert ET.fromstring(xml).find(".//JSONPostProcessor") is not None


def test_protocol_introspection_is_configuration_not_created_or_selected_data():
    value = "ApplicationSpecificType"
    entries = [
        exchange(
            "query Schema { __schema { types { name } } }",
            {"data": {"__schema": {"types": [{"name": value}]}}},
        ),
        exchange("query Type($name:String!) { __type(name:$name) { name } }", {}, {"name": value}, index=1),
    ]
    result = analyze({"log": {"entries": entries}})
    assert result.classification.by_value(value).classification == ValueClass.STATIC
    xml = build_jmx_xml(result).decode()
    assert value in xml and not result.correlations
    assert not any(c.sample == value for d in result.parameterization.datasets for c in d.columns)
    assert not ET.fromstring(xml).findall(".//JSONPostProcessor")


def test_unknown_read_payload_does_not_infer_master_data_from_shape_or_reuse():
    value = "d288057d-9ac1-47f5-bba4-4a99a4b337ab"
    entries = [
        exchange("query Context { opaque }", {"data": {"opaque": value}}),
        exchange("query Next($opaque:String!) { next(opaque:$opaque) }", {}, {"opaque": value}, index=1),
    ]
    result = analyze({"log": {"entries": entries}})
    assert result.classification.by_value(value).classification == ValueClass.UNKNOWN
    xml = build_jmx_xml(result).decode()
    assert not result.correlations
    assert any(r.value == value for r in result.parameterization.review)
    assert not any(c.sample == value for d in result.parameterization.datasets for c in d.columns)
    assert not ET.fromstring(xml).findall(".//JSONPostProcessor")


def test_ambiguous_operation_does_not_infer_creation_from_post_or_reuse():
    value = "applicationSpecificReference123"
    entries = [
        exchange(
            "query Read { record { ref } } mutation Write { create { ref } }",
            {"data": {"record": {"ref": value}}},
        ),
        exchange("query Detail($ref:ID!) { record(ref:$ref) { ref } }", {}, {"ref": value}, index=1),
    ]
    result = analyze({"log": {"entries": entries}})
    assert result.classification.by_value(value).classification == ValueClass.UNKNOWN
    xml = build_jmx_xml(result).decode()
    assert not result.correlations
    assert not any(c.sample == value for d in result.parameterization.datasets for c in d.columns)
    assert any(r.value == value for r in result.parameterization.review)
    assert ET.fromstring(xml).find(".//JSONPostProcessor") is None


def test_client_input_echo_does_not_become_a_runtime_identity():
    value = "userSelectedInput"
    entries = [
        exchange(
            "mutation Save($ref:ID!) { save(ref:$ref) { ref } }",
            {"data": {"save": {"ref": value}}},
            {"ref": value},
        ),
        exchange("query Detail($ref:ID!) { record(ref:$ref) { ref } }", {}, {"ref": value}, index=1),
    ]
    result = analyze({"log": {"entries": entries}})
    assert result.classification.by_value(value).lifecycle == Lifecycle.USER_INPUT
    assert not any(c.value == value for c in result.correlations)
    xml = build_jmx_xml(result).decode()
    assert not ET.fromstring(xml).findall(".//JSONPostProcessor")


@pytest.mark.parametrize("workflow,value", [("countries-graphql-5", "AD"), ("countries-graphql-6", "AE")])
def test_real_countries_capture_uses_existing_test_data_policy_when_available(workflow, value):
    path = Path(__file__).resolve().parents[2] / "real-world-benchmark/raw" / (workflow + ".har")
    if not path.exists():
        pytest.skip("External real benchmark corpus is not present in this checkout")
    result = analyze(path.read_bytes())
    verdict = result.classification.by_value(value)
    assert verdict.classification == ValueClass.BUSINESS_MASTER_DATA
    assert verdict.lifecycle == Lifecycle.EXISTING_BEFORE_RUN
    assert not any(c.value == value for c in result.correlations)
    xml = build_jmx_xml(result).decode()
    column = next(c for d in result.parameterization.datasets for c in d.columns if c.sample == value)
    doc = ET.fromstring(xml)
    consumer = doc.findall(".//HTTPSamplerProxy")[-1]
    body = consumer.find(".//stringProp[@name='Argument.value']").text
    assert json.loads(body)["variables"]["code"] == "${" + column.name + "}"
    assert "${countryCode}" not in xml
    assert not doc.findall(".//JSONPostProcessor")
    assert not validate_plan(result, xml)
