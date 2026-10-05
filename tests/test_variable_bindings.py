"""Variable ownership tests; discovery/classification are explicit frozen inputs."""
from __future__ import annotations

import csv
import json
from copy import deepcopy
from dataclasses import asdict
from xml.etree import ElementTree as ET

from har2jmx.correlate import CorrelationDecision, ExtractorType
from har2jmx.emit import build_jmx_xml, emit_jmx
from har2jmx.emit.bindings import VariableBindings, parameter_identity
from har2jmx.emit.redirects import location_variable
from har2jmx.engine import analyze
from har2jmx.parameterize.decide import ParameterColumn, ParameterDataset, ParameterizationPlan
from har2jmx.parameterize.intent import ParameterSlot
from har2jmx.validate import verify_extractors


def _result(name="route", input_value="Orders", runtime_value="Accounts", *, auth=False):
    entries = [
        {"request": {"method": "GET", "url": "https://example.test/start"},
         "response": {"status": 200, "content": {"mimeType": "application/json", "text": json.dumps({name: runtime_value})}}},
        {"request": {"method": "POST", "url": "https://example.test/update",
                     "postData": {"mimeType": "application/x-www-form-urlencoded",
                                  "params": [{"name": name, "value": input_value}]}},
         "response": {"status": 200, "content": {"text": "OK"}}},
        {"request": {"method": "GET", "url": f"https://example.test/status?{name}={runtime_value}"},
         "response": {"status": 200, "content": {"text": "OK"}}},
    ]
    result = analyze({"log": {"entries": entries}})
    location = f"request.body:{name}"
    slot = ParameterSlot(1, location, "body", name, input_value, input_value, "POST")
    column = ParameterColumn(name, input_value, intent="USER_INPUT", logical_field=name,
                             original=input_value, normalized=input_value, slots=[slot])
    result.parameterization = ParameterizationPlan([
        ParameterDataset("Inputs", [column], [{name: input_value}], "inputs")
    ])
    result.correlations = [CorrelationDecision(name, runtime_value, 0, f"response.body:{name}",
                                               ExtractorType.JSON, f"$.{name}", [2], "High")]
    if auth:
        result.capture.requests[2].request.headers.append(("Authorization", "Bearer " + runtime_value))
    result.extractor_checks = verify_extractors(result.capture, result.correlations)
    return result


def _arguments(root):
    return [
        {c.get("name"): c.text or "" for c in arg}
        for sampler in root.iter("HTTPSamplerProxy") for arg in sampler.iter("elementProp")
        if arg.get("elementType") == "HTTPArgument"
    ]


def test_csv_and_runtime_owners_receive_their_intended_values(tmp_path):
    result = _result()
    frozen = (asdict(result.parameterization), [asdict(c) for c in result.correlations], asdict(result.classification))
    name = VariableBindings(result).parameter_name(result.parameterization.datasets[0], result.parameterization.datasets[0].columns[0])
    path, csvs, _ = emit_jmx(result, tmp_path, {"threads": "1"})
    root = ET.parse(path).getroot()
    assert root.find(".//stringProp[@name='JSONPostProcessor.referenceNames']").text == "route"
    assert name != "route"
    rows = list(csv.reader(csvs[0].open(encoding="utf-8", newline="")))
    assert rows == [[name], ["Orders"]]
    args = _arguments(root)
    assert [a["Argument.value"] for a in args] == [f"${{{name}}}", "${route}"]
    # JMeter extracts runtime state after CSV initialization; isolated ownership
    # also works when the engineer supplies a different test-data row.
    variables = {name: "Changed Input", "route": "Fresh Runtime"}
    resolved = [variables[a["Argument.value"][2:-1]] for a in args]
    assert resolved == ["Changed Input", "Fresh Runtime"]
    assert frozen == (asdict(result.parameterization), [asdict(c) for c in result.correlations], asdict(result.classification))


def test_nonconflicting_csv_name_is_preserved():
    result = _result()
    result.correlations[0].variable = "runtime_route"
    bindings = VariableBindings(result)
    dataset = result.parameterization.datasets[0]
    assert bindings.parameter_name(dataset, dataset.columns[0]) == "route"


def test_owned_name_is_independent_of_sample_data_and_allocation_order():
    result = _result()
    before = VariableBindings(result).names
    other = deepcopy(result.parameterization.datasets[0])
    other.name = "SelectedRecords"
    result.parameterization.datasets.append(other)
    forward = VariableBindings(result).names
    result.parameterization.datasets.reverse()
    result.correlations.reverse()
    assert VariableBindings(result).names == forward
    result.parameterization.datasets.reverse()
    result.parameterization.datasets.pop()
    column = result.parameterization.datasets[0].columns[0]
    column.sample = column.original = column.normalized = "A Different Sample"
    result.parameterization.datasets[0].rows = [{column.name: "A Different Sample"}]
    assert VariableBindings(result).names == before


def test_distinct_dataset_identities_do_not_share_csv_variable():
    result = _result()
    dataset = result.parameterization.datasets[0]
    other = deepcopy(dataset)
    other.name = "ExistingRecord"
    result.parameterization.datasets.append(other)
    bindings = VariableBindings(result)
    assert parameter_identity(dataset, dataset.columns[0]) != parameter_identity(other, other.columns[0])
    assert bindings.parameter_name(dataset, dataset.columns[0]) != bindings.parameter_name(other, other.columns[0])


def test_preexisting_owned_looking_runtime_name_is_not_overwritten():
    result = _result()
    dataset = result.parameterization.datasets[0]
    first = VariableBindings(result).parameter_name(dataset, dataset.columns[0])
    extra = deepcopy(result.correlations[0])
    extra.variable = first
    result.correlations.append(extra)
    bindings = VariableBindings(result)
    assert bindings.parameter_name(dataset, dataset.columns[0]) not in {"route", first}


def test_plan_and_redirect_variable_ownership_is_reserved():
    for name in ["THREADS", location_variable(1)]:
        result = _result(name)
        result.correlations = []
        dataset = result.parameterization.datasets[0]
        assert VariableBindings(result).parameter_name(dataset, dataset.columns[0]) != name


def test_auth_runtime_name_checks_and_header_binding_remain_intact():
    result = _result("access_token", "Engineer Supplied Input", "SERVER_TOKEN_123", auth=True)
    root = ET.fromstring(build_jmx_xml(result))
    assert root.find(".//stringProp[@name='JSONPostProcessor.referenceNames']").text == "access_token"
    assert any(p.text == "Bearer ${access_token}" for p in root.iter("stringProp"))
    assert any("'access_token'" in (p.text or "") for p in root.iter("stringProp") if p.get("name") == "script")
    dataset = result.parameterization.datasets[0]
    owned = VariableBindings(result).parameter_name(dataset, dataset.columns[0])
    assert f"${{{owned}}}" in [a["Argument.value"] for a in _arguments(root)]


def test_repeated_emission_keeps_owned_names_and_csv_bytes(tmp_path):
    result = _result()
    first, csvs, _ = emit_jmx(result, tmp_path / "first", {"threads": "1"})
    second, again, _ = emit_jmx(result, tmp_path / "second", {"threads": "1"})
    assert first.read_bytes() == second.read_bytes()
    assert csvs[0].read_bytes() == again[0].read_bytes()


def test_conflicting_input_initial_row_comes_from_its_owned_source_slot(tmp_path):
    result = _result()
    dataset = result.parameterization.datasets[0]
    dataset.columns[0].sample = "Wrong Entity Sample"
    dataset.rows = [{"route": "Wrong Entity Sample"}, {"route": "Other Observed Entity"}]
    frozen = asdict(result.parameterization)
    _, csvs, _ = emit_jmx(result, tmp_path, {"threads": "1"})
    rows = list(csv.reader(csvs[0].open(encoding="utf-8", newline="")))
    assert rows[1:] == [["Orders"], ["Other Observed Entity"]]
    assert asdict(result.parameterization) == frozen


def test_multiple_captured_values_are_not_forced_into_one_initial_binding():
    result = _result()
    dataset = result.parameterization.datasets[0]
    dataset.columns[0].slots.append(ParameterSlot(2, "request.body:route", "body", "route", "Another Input", "Another Input"))
    dataset.rows = [{"route": "Other Observed Entity"}]
    assert VariableBindings(result).parameter_rows(dataset) == dataset.rows
