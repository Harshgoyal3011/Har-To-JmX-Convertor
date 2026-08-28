"""Enterprise scenario — OAuth2 authorization-code redirect chain."""
from __future__ import annotations

from pathlib import Path

from har2jmx.emit import build_jmx_xml
from har2jmx.engine import analyze

FIX = Path(__file__).parent / "fixtures"
CODE = "AUTHCODE-9f8e7d6c5b4a3210"


def _res():
    return analyze((FIX / "sample_oauth.har").read_bytes())


def test_oauth_and_oidc_detected():
    names = {m.name for m in _res().auth.mechanisms}
    assert "OAuth2" in names and "OpenID Connect" in names


def test_auth_code_from_redirect_is_correlated():
    r = _res()
    code = next((c for c in r.correlations if c.variable == "code"), None)
    assert code is not None and code.value == CODE
    assert code.extractor.value == "regex" and code.from_redirect
    # consumed by /callback and /token
    assert len(code.consumers) >= 2


def test_access_token_correlated():
    assert any(c.variable == "access_token" for c in _res().correlations)


def test_emitted_plan_handles_redirect_and_hides_code():
    x = build_jmx_xml(_res()).decode()
    assert "${code}" in x                          # code flows via variable, not hardcoded
    assert CODE not in x                            # single-use code never ships literally
    assert 'follow_redirects">false' in x          # authorize step must not follow the 302


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for fn in fns:
        try:
            fn()
        except AssertionError as e:
            print(f"FAIL  {fn.__name__}: {e}")
        except Exception as e:
            print(f"ERROR {fn.__name__}: {type(e).__name__}: {e}")
        else:
            passed += 1
            print(f"ok    {fn.__name__}")
    print(f"\n{passed}/{len(fns)} passed")
    raise SystemExit(0 if passed == len(fns) else 1)
