"""Stateful multi-step flows: rotating CSRF tokens, and logout + re-login (session change)."""
from __future__ import annotations

import re
from pathlib import Path

from har2jmx.emit import build_jmx_xml
from har2jmx.emit.validate import validate_plan
from har2jmx.engine import analyze

FIX = Path(__file__).parent / "fixtures"


def _analyze(name: str):
    return analyze((FIX / name).read_bytes())


def test_rotating_csrf_token_reextracted_each_step():
    # a double-submit CSRF token changes on every response; each step must send the token from the
    # PRECEDING response, not a single captured value.
    r = _analyze("sample_csrf_rotation.har")
    by_var = {c.variable: c.value for c in r.correlations}
    assert by_var.get("csrf") == "CSRF-tok-111"     # from the initial form
    assert by_var.get("csrf2") == "CSRF-tok-222"    # rotated by step 1's response
    x = build_jmx_xml(r).decode()
    # step 1 posts ${csrf}, step 2 posts ${csrf2}; no literal token ships
    bodies = re.findall(r"Argument.value\">(\$\{csrf\d?\})", x)
    assert bodies == ["${csrf}", "${csrf2}"]
    assert "CSRF-tok-111" not in x and "CSRF-tok-222" not in x
    assert validate_plan(r, x) == []


def test_logout_then_relogin_names_and_session_handling():
    # a logout + re-login recaptures a new session id; the flow reads correctly and the Cookie Manager
    # carries both sessions across the teardown.
    r = _analyze("sample_logout.har")
    names = [t.name for t in r.transactions]
    assert names == ["Login", "View Dashboard", "Logout", "Login (2)", "View Dashboard (2)"]
    # both session ids are handled by the Cookie Manager (never re-sent as a manual Cookie header)
    x = build_jmx_xml(r).decode()
    assert "SESS-first-111" not in x and "SESS-second-222" not in x
    assert 'testname="HTTP Cookie Manager"' in x
    assert validate_plan(r, x) == []


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
