"""Embedded / boundary correlation + search-input parameterization (real-app patterns)."""
from __future__ import annotations

from pathlib import Path

from har2jmx.classify import ValueClass, classify_capture, classify_values
from har2jmx.emit import build_jmx_xml
from har2jmx.emit.validate import validate_plan
from har2jmx.engine import analyze
from har2jmx.ir.build import build_capture

FIX = Path(__file__).parent / "fixtures"


def test_token_wrapped_in_a_response_string_is_correlated_via_boundary():
    # the token comes back embedded ("Auth_token: <t>"), not as its own JSON field, so whole-slot
    # matching misses it. A boundary/regex extractor must pull it out and feed it downstream.
    r = analyze((FIX / "sample_embedded_token.har").read_bytes())
    corr = {c.variable: c for c in r.correlations}
    tok = next((c for c in r.correlations if c.value == "kd93JafeL0aZ2p"), None)
    assert tok is not None                                  # the wrapped token is correlated
    assert tok.extractor.value == "regex" and "Auth_token" in tok.expression
    x = build_jmx_xml(r).decode()
    # the token ships only inside the extractor's own regex, never hardcoded in a request body
    assert '"token":"kd93JafeL0aZ2p"' not in x and '"cookie":"kd93JafeL0aZ2p"' not in x
    assert validate_plan(r, x) == []


def test_no_false_embedded_match_for_short_or_unanchored_values():
    # embedded matching is conservative: it must not fabricate correlations from short/coincidental
    # substrings — the sample flow has none, so nothing new should appear as a regex body extractor.
    cap = build_capture((FIX / "sample_flow.har").read_bytes())
    classify_capture(cap)
    r = classify_values(cap)
    assert all("response.regex:" not in v.source for v in r.correlations())


def test_category_and_search_selection_is_parameterized():
    # a category / search term the user picks is business input that should vary per user — the
    # expert parameterized product selections; a clearly-named field must not be left hardcoded.
    r = analyze((FIX / "sample_search.har").read_bytes())
    params = {c.name for d in r.parameterization.datasets for c in d.columns}
    assert "cat" in params                                  # category selection parameterized
    assert "monitor" not in build_jmx_xml(r).decode() or "${cat}" in build_jmx_xml(r).decode()


def test_embedded_producer_found_within_scan_window():
    # guards the bounded-scan optimization: an embedded token issued shortly before its use must still
    # be correlated. A token is embedded in an earlier response string and reused a few requests later;
    # the windowed scan (nearest prior responses) must still find the producer via a boundary extractor.
    import json
    from har2jmx.lineage import build_lineage

    tok = "Zx91KkQ7mPa2Ld"
    entries = []
    for i in range(6):
        body = f"prelude noise Auth_token: {tok}; more" if i == 2 else "nothing here"
        entries.append({"startedDateTime": f"2026-01-01T00:00:0{i}Z", "time": 5,
            "request": {"method": "GET", "url": f"https://a.com/step/{i}", "headers": [], "cookies": []},
            "response": {"status": 200, "headers": [{"name": "Content-Type", "value": "text/plain"}],
                         "content": {"mimeType": "text/plain", "text": body}}})
    entries.append({"startedDateTime": "2026-01-01T00:00:06Z", "time": 5,
        "request": {"method": "GET", "url": "https://a.com/use",
                    "headers": [{"name": "X-Auth-Token", "value": tok}], "cookies": []},
        "response": {"status": 200, "headers": [], "content": {"mimeType": "text/plain", "text": "ok"}}})
    cap = build_capture(json.dumps({"log": {"version": "1.2", "entries": entries}}).encode())
    classify_capture(cap)
    flow = build_lineage(cap).by_value(tok)
    assert flow is not None and flow.first_producer is not None            # producer found in window
    assert flow.first_producer.location.startswith("response.regex:")      # via boundary extractor
    assert flow.first_producer.request_index == 2                          # the response that embedded it


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
