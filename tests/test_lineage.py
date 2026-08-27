"""Milestone 7 tests — value lineage / dependency graph.

Runs under pytest, and also directly:  PYTHONPATH=src python tests/test_lineage.py
"""
from __future__ import annotations

from pathlib import Path

from har2jmx.classify import classify_capture
from har2jmx.ir.build import build_capture
from har2jmx.lineage import build_lineage

FIX = Path(__file__).parent / "fixtures"


def _graph(name: str):
    cap = build_capture((FIX / name).read_bytes())
    classify_capture(cap)
    return build_lineage(cap)


def test_cookie_token_producer_and_consumer():
    g = _graph("sample_lineage.har")
    f = g.by_value("SID-abc123def")
    assert f is not None
    assert f.first_producer is not None and f.first_producer.request_index == 0   # Set-Cookie at login
    assert f.first_producer.location.startswith("set-cookie:")
    assert f.consumer_indices == [1]                                              # replayed cookie, only req 1


def test_no_substring_false_consumers():
    # "SID-abc123def" must NOT be consumed by req 2 (body label "SID-banner-text") or req 4 (?code=SID)
    g = _graph("sample_lineage.har")
    f = g.by_value("SID-abc123def")
    assert 2 not in f.consumer_indices
    assert 4 not in f.consumer_indices


def test_transform_json_string_to_path_segment():
    # orderId "OX-9klm" produced in a JSON response, consumed as a URL path segment.
    g = _graph("sample_lineage.har")
    f = g.by_value("OX-9klm")
    assert f.first_producer.request_index == 2 and f.first_producer.location.startswith("response.body:")
    assert 3 in f.consumer_indices
    assert any(o.location == "request.path" for o in f.consumers)


def test_numeric_int_matches_across_json_and_path():
    # userId 500: JSON int in a response, later a path segment and a JSON body int.
    g = _graph("sample_lineage.har")
    f = g.by_value("500")   # string form matches the JSON integer 500
    assert f.is_produced_then_consumed
    assert 1 in f.consumer_indices     # /api/users/500 path
    assert 2 in f.consumer_indices     # {"userId":500} body


def test_request_only_values_have_no_producer():
    g = _graph("sample_lineage.har")
    label = g.by_value("SID-banner-text")
    assert label is not None and not label.producers        # only ever in a request body
    assert label not in g.produced_then_consumed()


def test_excluded_requests_ignored():
    # sample_mini: the /eum/ beacon and static svg are excluded and must not appear in lineage.
    g = _graph("sample_mini.har")
    for f in g.flows:
        assert all(o.request_index not in (2, 3) for o in f.occurrences)


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for fn in fns:
        try:
            fn()
        except AssertionError as e:
            print(f"FAIL  {fn.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            print(f"ERROR {fn.__name__}: {type(e).__name__}: {e}")
        else:
            passed += 1
            print(f"ok    {fn.__name__}")
    print(f"\n{passed}/{len(fns)} passed")
    raise SystemExit(0 if passed == len(fns) else 1)
