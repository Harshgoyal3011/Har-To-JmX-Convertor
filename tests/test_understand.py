"""Milestone 3 tests — application & auth understanding (evidence-gated).

Runs under pytest, and also directly:  PYTHONPATH=src python tests/test_understand.py
"""
from __future__ import annotations

from pathlib import Path

from har2jmx.ir.build import build_capture
from har2jmx.understand import detect_application, detect_auth

FIX = Path(__file__).parent / "fixtures"


def _cap(name: str):
    return build_capture((FIX / name).read_bytes())


def test_api_styles_rest_and_graphql():
    app = detect_application(_cap("sample_mini.har"))
    names = {d.name for d in app.api_styles}
    assert "GraphQL" in names
    assert "REST" in names


def test_auth_oauth_and_cookie_session_on_mini():
    auth = detect_auth(_cap("sample_mini.har"))
    names = {d.name for d in auth.mechanisms}
    assert "OAuth2" in names          # /connect/authorize
    assert "Cookie session" in names  # SESSIONID set then replayed


def test_no_detection_without_evidence():
    # sample_noise.har has no auth artifacts → no auth mechanisms claimed.
    auth = detect_auth(_cap("sample_noise.har"))
    assert auth.mechanisms == []
    assert auth.primary is None
    assert auth.token_refresh is False


def test_server_stack_aspnet():
    app = detect_application(_cap("sample_auth_stack.har"))
    names = {d.name for d in app.server_stack}
    assert "ASP.NET" in names
    aspnet = next(d for d in app.server_stack if d.name == "ASP.NET")
    assert aspnet.confidence == "High" and aspnet.evidence  # evidence-backed


def test_auth_stack_full_detection():
    auth = detect_auth(_cap("sample_auth_stack.har"))
    names = {d.name for d in auth.mechanisms}
    assert "Bearer/JWT" in names
    assert "OAuth2" in names
    assert "OpenID Connect" in names          # id_token in token response
    assert "SAML" in names
    assert "Kerberos/Negotiate (SPNEGO)" in names
    assert "Cookie session" in names          # ASP.NET_SessionId set then replayed
    assert auth.token_refresh is True         # grant_type=refresh_token
    assert auth.primary == "Bearer/JWT"       # strongest by priority


def test_every_detection_has_evidence():
    for name in ("sample_mini.har", "sample_auth_stack.har"):
        app = detect_application(_cap(name))
        auth = detect_auth(_cap(name))
        for group in (app.api_styles, app.server_stack, app.spa_frameworks, app.enterprise_platforms, auth.mechanisms):
            for d in group:
                assert d.evidence, f"{d.name} has no evidence"


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
