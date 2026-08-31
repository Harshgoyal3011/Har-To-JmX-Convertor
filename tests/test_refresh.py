"""OAuth2 refresh-token flow — correlation, transaction naming, and expiry-failure handling."""
from __future__ import annotations

from pathlib import Path

from har2jmx.classify.request_noise import is_token_refresh
from har2jmx.emit import build_jmx_xml
from har2jmx.emit.validate import validate_plan
from har2jmx.engine import analyze

FIX = Path(__file__).parent / "fixtures"


def _result():
    return analyze((FIX / "sample_refresh.har").read_bytes())


def test_refresh_request_detected_structurally():
    r = _result()
    refresh = [rq for rq in r.capture.requests if is_token_refresh(rq)]
    assert len(refresh) == 1
    assert refresh[0].request.path.endswith("/token")   # grant_type=refresh_token, not by name
    # the initial password login is NOT a refresh
    assert not is_token_refresh(r.capture.requests[0])


def test_refresh_does_not_hijack_the_user_action_name():
    # a token refresh is background machinery — the surrounding action stays "View Orders", and the
    # refresh never mislabels a transaction as "Login".
    r = _result()
    names = [t.name for t in r.transactions]
    assert names == ["Login", "View Profile", "View Orders", "View Settings"]


def test_expiry_401_is_superseded_and_dropped():
    # the recorded 401 (expired token) is followed by a refresh + a successful retry of the same
    # endpoint, so it is excluded — the load script has no built-in failure.
    r = _result()
    failed = r.capture.requests[2]
    assert failed.status == 401 and failed.classification.excluded
    x = build_jmx_xml(r).decode()
    # only the successful /api/orders retry ships (2 orders requests recorded, 1 in the plan)
    assert x.count("HTTPSampler.path\">/api/orders<") == 1


def test_first_token_keeps_base_name_refresh_is_suffixed():
    r = _result()
    by_var = {c.variable: c.value for c in r.correlations}
    assert by_var.get("access_token") == "AT-login-1111aaaa"     # first issued keeps the base name
    assert by_var.get("access_token2") == "AT-refresh-3333cccc"  # the refreshed one is suffixed
    assert by_var.get("refresh_token") == "RT-seed-2222bbbb"     # sent in the refresh body


def test_calls_use_the_correct_token_before_and_after_refresh():
    r = _result()
    x = build_jmx_xml(r).decode()
    # the refreshed token never ships as a literal
    assert "AT-refresh-3333cccc" not in x and "AT-login-1111aaaa" not in x
    # pre-refresh call carries the login token; post-refresh calls carry the refreshed token
    import re
    bearers = re.findall(r"Bearer (\$\{[^}]+\})", x)
    assert bearers == ["${access_token}", "${access_token2}", "${access_token2}"]


def test_refresh_plan_is_production_clean():
    r = _result()
    assert validate_plan(r, build_jmx_xml(r).decode()) == []


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
