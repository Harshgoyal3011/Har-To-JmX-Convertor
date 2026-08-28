"""Enterprise scenario — stateful SOAP (XML value correlation, SOAPAction naming)."""
from __future__ import annotations

from pathlib import Path

from har2jmx.emit import build_jmx_xml
from har2jmx.engine import analyze

FIX = Path(__file__).parent / "fixtures"


def _res():
    return analyze((FIX / "sample_soap.har").read_bytes())


def test_soap_detected_and_named_from_operation():
    r = _res()
    assert "SOAP" in {d.name for d in r.application.api_styles}
    assert [t.name for t in r.transactions] == ["Login", "Get Order", "Update Order"]


def test_xml_session_and_id_correlated():
    r = _res()
    vals = {c.variable: c.value for c in r.correlations}
    assert "SessionId" in vals                    # runtime session from the XML response
    assert "orderId" in vals                       # server-returned id reused later


def test_user_input_parameterized():
    cols = {c.name for d in _res().parameterization.datasets for c in d.columns}
    assert "orderNumber" in cols


def test_emitted_plan_substitutes_xml_values():
    x = build_jmx_xml(_res()).decode()
    assert "${SessionId}" in x and "${orderId}" in x
    assert "SESS-7a9f2c1e-4b8d-11ef" not in x       # literal session never ships


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
