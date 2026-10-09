"""P2-4A identities are inspection evidence, with no decision mutations."""

import json
from copy import deepcopy
from dataclasses import asdict

from har2jmx.emit import build_jmx_xml
from har2jmx.engine import analyze
from har2jmx.ir.normalized import BodyKind
from har2jmx.lineage import build_lineage, build_occurrence_index


def event(host="a.test", response=None, body=None, headers=(), url=None):
    request = {
        "method": "POST",
        "url": url or f"https://{host}/issue",
        "headers": [{"name": n, "value": v} for n, v in headers],
    }
    if body is not None:
        request["postData"] = {"mimeType": "application/json", "text": json.dumps(body)}
    return {
        "request": request,
        "response": {
            "status": 201,
            "content": {"mimeType": "application/json", "text": json.dumps(response or {})},
        },
    }


def index(events):
    result = analyze({"log": {"entries": events}})
    return result, build_occurrence_index(result.capture)


def test_r05_foundation_distinguishes_owners_without_repairing_behavior():
    result, occurrences = index(
        [
            event(response={"orderId": "1001"}),
            event("b.test", response={"accountId": "1001"}),
            event("b.test", body={"accountId": "1001"}),
        ]
    )
    producers = [o for o in occurrences.literal_evidence("1001") if o.side == "response"]
    assert len(producers) == 2
    assert len({o.identity for o in producers}) == 2
    assert len({o.origin for o in producers}) == 2
    assert len({o.source_response_identity for o in producers}) == 2
    # The deliberately frozen legacy decision still demonstrates R05.
    assert result.correlations[0].producer_index == 0
    assert result.correlations[0].variable == "orderId"
    assert "${orderId}" in build_jmx_xml(result).decode()


def test_repeat_request_and_same_host_field_remain_separate():
    repeated = event(response={"orderId": "1001"})
    _, occurrences = index([repeated, deepcopy(repeated)])
    values = [o for o in occurrences.literal_evidence("1001") if o.side == "response"]
    assert len({o.identity for o in values}) == len({o.event_identity for o in values}) == 2
    assert {o.request_index for o in values} == {0, 1}


def test_array_positions_scalar_arrays_and_literal_dotted_keys():
    _, occurrences = index(
        [
            event(
                response={
                    "items": [{"id": "1001"}, {"id": "1001"}],
                    "scalar": ["1001", "1001"],
                    "items.id": "1001",
                }
            )
        ]
    )
    values = [o for o in occurrences.literal_evidence("1001") if o.side == "response"]
    assert len(values) == len({o.identity for o in values}) == 5
    assert {o.structured_path for o in values} == {
        ("items", 0, "id"),
        ("items", 1, "id"),
        ("scalar", 0),
        ("scalar", 1),
        ("items.id",),
    }


def test_original_scalar_types_are_not_identity_collapsed():
    _, occurrences = index(
        [event(response={"a": 1001, "b": "1001", "c": 1001.0, "flag": True, "empty": None})]
    )
    values = [o for o in occurrences.occurrences if o.side == "response"]
    assert {o.original_type for o in values} == {"integer", "string", "number", "boolean", "null"}
    equal = occurrences.literal_evidence("1001")
    assert len(equal) == 2 and equal[0].identity != equal[1].identity


def test_header_body_and_scheme_have_distinct_occurrence_coordinates():
    _, occurrences = index(
        [
            event(
                body={"token": "freshToken123"},
                headers=[("Authorization", "Bearer freshToken123"), ("X-Token", "freshToken123")],
            )
        ]
    )
    values = occurrences.literal_evidence("freshToken123")
    assert len(values) == 3 and len({o.identity for o in values}) == 3
    payload = next(o for o in values if o.representation_kind == "credential_payload")
    parent = occurrences.by_identity(payload.representation_parent)
    assert parent.original_spelling == "Bearer freshToken123"
    assert payload.transforms == ("credential_scheme_removed",)


def test_encoded_decoded_and_duplicate_query_pairs_keep_provenance():
    _, occurrences = index(
        [event(response={"token": "A B+123"}, url="https://a.test/use?token=A%20B%2B123&token=A+B%2B123")]
    )
    values = occurrences.literal_evidence("A B+123")
    assert len(values) == len({o.identity for o in values}) == 3
    queries = [o for o in values if o.representation_kind == "url_query_value"]
    assert {o.pair_index for o in queries} == {0, 1}
    assert {o.original_spelling for o in queries} == {"A%20B%2B123", "A+B%2B123"}
    assert all("url_form_decode" in o.transforms for o in queries)
    assert all(o.representation_parent is None for o in queries)  # no invented response lineage


def test_inventory_is_deterministic_and_does_not_mutate_existing_decisions():
    result, _ = index([event(response={"orderId": "1001"}), event(body={"orderId": "1001"})])
    lineage = build_lineage(result.capture)
    frozen = deepcopy((asdict(result), asdict(lineage)))
    before_jmx = build_jmx_xml(result)
    first = build_occurrence_index(result.capture, lineage)
    second = build_occurrence_index(result.capture, lineage)
    assert first.inspect() == second.inspect()
    assert frozen == (asdict(result), asdict(lineage))
    assert before_jmx == build_jmx_xml(result)
    assert all(first.by_identity(o.identity) is o for o in first.occurrences)


def test_capture_scope_prevents_cross_capture_identity_alias():
    result, _ = index([event(response={"orderId": "1001"})])
    a = build_occurrence_index(result.capture, capture_identity="capture-a")
    b = build_occurrence_index(result.capture, capture_identity="capture-b")
    assert {o.identity for o in a.occurrences}.isdisjoint(o.identity for o in b.occurrences)


def test_json_beyond_legacy_limits_is_inspection_only():
    result, occurrences = index([event(response={"items": [{"id": str(1000 + i)} for i in range(40)]})])
    last = next(o for o in occurrences.occurrences if o.structured_path == ("items", 39, "id"))
    assert last.literal_compatibility_bucket is None
    assert build_lineage(result.capture).by_value("1039") is None


def test_identity_coordinates_do_not_depend_on_literal_sample():
    first, _ = index([event(response={"orderId": "1001"})])
    second, _ = index([event(response={"orderId": "2002"})])
    a = build_occurrence_index(first.capture, capture_identity="persistent-capture")
    b = build_occurrence_index(second.capture, capture_identity="persistent-capture")
    a_value = next(o for o in a.occurrences if o.side == "response")
    b_value = next(o for o in b.occurrences if o.side == "response")
    assert a_value.identity == b_value.identity
    assert a_value.normalized_representation != b_value.normalized_representation


def test_duplicate_transport_pairs_have_distinct_pair_identity():
    result, _ = index([event(headers=[("X-Token", "1001"), ("X-Token", "1001")])])
    result.capture.requests[0].request.body.form = [("name", "Alice"), ("name", "Alice")]
    result.capture.requests[0].request.body.kind = BodyKind.FORM
    occurrences = build_occurrence_index(result.capture)
    headers = occurrences.literal_evidence("1001")
    forms = occurrences.literal_evidence("Alice")
    assert len(headers) == len({o.identity for o in headers}) == 2
    assert len(forms) == len({o.identity for o in forms}) == 2
    assert {o.pair_index for o in headers} == {o.pair_index for o in forms} == {0, 1}
    assert all(not o.array_indices for o in headers + forms)


def test_nested_percent_encoding_evidence_lookup_does_not_decode_key_twice():
    result, _ = index([event(response={"value": "A%2520B123"})])
    lineage = build_lineage(result.capture)
    occurrences = build_occurrence_index(result.capture, lineage)
    key = next(f.value for f in lineage.flows if f.value == "A%20B123")
    assert occurrences.literal_evidence(key)
    assert occurrences.literal_evidence(key)[0].literal_compatibility_bucket == key
