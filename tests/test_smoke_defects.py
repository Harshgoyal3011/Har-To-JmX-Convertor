"""Regression tests for defects found by the cross-application smoke test.

Each test pins a specific defect observed on a real demo-app capture:
  - file-extension leaking into a transaction name (openlibrary /search.json)
  - a "Bearer <token>" wrapper double-flagged as an uncaptured secret (banking/healthcare/oauth/refresh)
  - public OAuth config (client_id) and a client nonce (state) flagged as secrets (oauth)
  - a genuinely uncaptured token must still flag (must not be over-suppressed)
  - an error-dominated capture (all 4xx/5xx) must be called out, not sold as ready (petstore)
"""
from __future__ import annotations

from har2jmx.classify import classify_capture
from har2jmx.engine import analyze
from har2jmx.ir.build import build_capture
from har2jmx.webreport import assess_capture_quality, build_manual_correlations
from har2jmx.workflow import discover_transactions


def _entry(method, url, status=200, resp_body="", req_headers=None, req_body=None, ct="application/json"):
    e = {
        "startedDateTime": "2026-01-01T10:00:00.000Z", "time": 20,
        "request": {"method": method, "url": url,
                    "headers": [{"name": k, "value": v} for k, v in (req_headers or {}).items()],
                    "cookies": []},
        "response": {"status": status, "headers": [{"name": "Content-Type", "value": ct}],
                     "content": {"mimeType": ct, "text": resp_body}},
    }
    if req_body is not None:
        e["request"]["postData"] = {"mimeType": "application/json", "text": req_body}
    return e


def _har(entries):
    return {"log": {"version": "1.2", "entries": entries}}


def test_file_extension_stripped_from_transaction_name():
    cap = build_capture(_har([
        _entry("GET", "https://openlibrary.org/search.json?q=performance", resp_body='{"numFound":6}'),
        _entry("GET", "https://openlibrary.org/works/OL45883W.json", resp_body='{"key":"/works/OL45883W"}'),
    ]))
    classify_capture(cap)
    names = [t.name for t in discover_transactions(cap)]
    assert "Search" in names                      # not "Search.json Search"
    assert not any(".json" in n for n in names)   # no extension leaks into any name


def test_bearer_wrapper_not_flagged_when_token_is_correlated():
    # login issues access_token; a later request sends "Authorization: Bearer <token>". The token is
    # correlated on its own — the scheme wrapper must NOT also appear as a manual-correlation item.
    r = analyze(_har([
        _entry("POST", "https://api.x.com/login", resp_body='{"access_token":"AT-abc123def456"}',
               req_body='{"u":"a"}'),
        _entry("GET", "https://api.x.com/me", req_headers={"Authorization": "Bearer AT-abc123def456"},
               resp_body='{"id":7}'),
    ]))
    assert any(c.variable == "access_token" for c in r.correlations)   # token IS correlated
    manual = build_manual_correlations(r)
    assert not any("Bearer" in m["value"] or m["field"].lower() == "authorization" for m in manual)


def test_oauth_client_id_and_state_not_flagged_as_secret():
    r = analyze(_har([
        _entry("GET", "https://app.x.com/callback?code=CODE-xyz789abc&state=stateABC123",
               resp_body='{"ok":true}'),
        _entry("POST", "https://idp.x.com/token",
               req_body="grant_type=authorization_code&code=CODE-xyz789abc&client_id=myapp&state=stateABC123",
               resp_body='{"access_token":"AT-99887766"}', ct="application/x-www-form-urlencoded"),
    ]))
    manual = build_manual_correlations(r)
    flagged = {m["field"].lower() for m in manual}
    assert "client_id" not in flagged and "state" not in flagged


def test_genuine_uncaptured_token_still_flags():
    # a request carries a session token whose issuing response was never captured — this MUST still be
    # flagged for manual correlation (the false-positive fixes must not over-suppress the real case).
    r = analyze(_har([
        _entry("GET", "https://api.x.com/orders",
               req_headers={"X-Session-Token": "sess-9f8e7d6c5b4a3210"}, resp_body='{"orders":[]}'),
    ]))
    manual = build_manual_correlations(r)
    assert manual, "a genuinely uncaptured token must still be flagged"
    assert any("sess" in m["value"] or "session" in m["field"].lower() for m in manual)


def test_freetext_user_input_is_parameterized():
    # a GenAI/content app's free-text input (the prompt/message the user types) is THE variable to vary
    # per user — it must be parameterized, not shipped hardcoded (same prompt x N users tests nothing).
    r = analyze(_har([
        _entry("POST", "https://api.x.com/login", resp_body='{"access_token":"AT-abc123def456"}',
               req_body='{"email":"a@x.com","password":"p"}'),
        _entry("POST", "https://api.x.com/conversations", status=201,
               req_headers={"Authorization": "Bearer AT-abc123def456"},
               req_body='{"title":"Chat"}', resp_body='{"conversationId":"conv_7h3k9m2p"}'),
        _entry("POST", "https://api.x.com/conversations/conv_7h3k9m2p/messages", status=201,
               req_headers={"Authorization": "Bearer AT-abc123def456"},
               req_body='{"role":"user","content":"Explain how to size a load test"}',
               resp_body='{"messageId":"msg_a1b2c3"}'),
    ]))
    cols = {c.name for d in r.parameterization.datasets for c in d.columns}
    assert "content" in cols, f"free-text prompt not parameterized; params={cols}"


def test_error_dominated_capture_is_flagged():
    cap = build_capture(_har([
        _entry("POST", "https://petstore.x.io/store/order", status=500, resp_body='{"code":500}',
               req_body='{"a":1}'),
        _entry("GET", "https://petstore.x.io/store/order/10", status=500, resp_body='{"code":500}'),
        _entry("GET", "https://petstore.x.io/pet/findByStatus?status=available", status=500,
               resp_body='{"code":500}'),
    ]))
    classify_capture(cap)
    q = assess_capture_quality(cap)
    assert q["errorPct"] == 100 and q["errorDominated"] is True and q["degraded"] is True

    # a capture with a working core flow (only the tail failed) is NOT error-dominated
    cap2 = build_capture(_har([
        _entry("POST", "https://api.x.com/login", resp_body='{"access_token":"AT-1"}', req_body='{"u":"a"}'),
        _entry("GET", "https://api.x.com/products", resp_body='[{"id":1}]'),
        _entry("POST", "https://api.x.com/products", status=500, resp_body='{"e":1}', req_body='{"n":"x"}'),
    ]))
    classify_capture(cap2)
    q2 = assess_capture_quality(cap2)
    assert q2["errorDominated"] is False


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
