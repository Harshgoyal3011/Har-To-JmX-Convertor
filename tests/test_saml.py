"""Enterprise scenario — SAML SSO (SP-initiated POST binding, cross-domain)."""
from __future__ import annotations

from pathlib import Path

from har2jmx.emit import build_jmx_xml, validate_plan
from har2jmx.engine import analyze

FIX = Path(__file__).parent / "fixtures"


def _res():
    return analyze((FIX / "sample_saml.har").read_bytes())


def test_saml_detected():
    assert "SAML" in {m.name for m in _res().auth.mechanisms}


def test_all_saml_dynamic_values_correlated():
    r = _res()
    v = {c.variable: c for c in r.correlations}
    assert "SAMLRequest" in v                     # generated in the SP->IdP redirect
    assert "SAMLResponse" in v                    # IdP's base64 assertion in the auto-post form
    assert "RelayState" in v                      # passed through the whole flow
    assert v["SAMLResponse"].extractor.value == "regex"   # extracted from HTML
    assert "SPSESSION" in v and v["SPSESSION"].extractor.value == "cookie_manager"


def test_saml_plan_is_clean_and_hides_assertion():
    r = _res()
    x = build_jmx_xml(r).decode()
    assert not validate_plan(r, x)                # production-clean
    saml_resp = next(c.value for c in r.correlations if c.variable == "SAMLResponse")
    assert saml_resp not in x                     # the assertion flows via ${SAMLResponse}, not hardcoded


def test_saml_transaction_names():
    assert [t.name for t in _res().transactions] == ["Launch Application", "Login"]


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
