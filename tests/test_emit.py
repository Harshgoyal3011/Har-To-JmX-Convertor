"""Milestone 12 (cutover) — JMX emitter tests."""
from __future__ import annotations

from pathlib import Path
from xml.dom import minidom

from har2jmx.emit import build_jmx_xml
from har2jmx.engine import analyze

FIX = Path(__file__).parent / "fixtures"
EXAMPLES = Path(__file__).parent.parent / "examples"


def _xml(har_path: Path) -> str:
    result = analyze(har_path.read_bytes())
    data = build_jmx_xml(result, {"threads": "25", "loops": "3", "ramp": "10"})
    minidom.parseString(data)                     # must be well-formed XML
    return data.decode("utf-8")


def test_plan_is_valid_and_parametric_for_n_users():
    x = _xml(FIX / "sample_flow.har")
    assert x.startswith("<?xml")
    assert "${THREADS}" in x and "${LOOPS}" in x and "${RAMP}" in x
    assert 'name="THREADS"' in x and ">25<" in x   # configured N users


def test_transactions_and_extractor_present():
    x = _xml(FIX / "sample_flow.har")
    assert "TransactionController" in x
    assert "Create Order" in x and "Login" in x
    assert "JSONPostProcessor" in x                # orderId correlation extractor
    assert "referenceNames" in x and "orderId" in x


def test_global_header_manager_in_every_plan():
    # a plan always has an HTTP Header Manager at the thread group (like the Cookie Manager),
    # holding the headers common to all requests — not repeated on every sampler.
    result = analyze((FIX / "sample_browser.har").read_bytes())
    x = build_jmx_xml(result).decode()
    assert 'testname="HTTP Header Manager"' in x
    import re
    block = re.search(r'HTTP Header Manager.*?</hashTree>', x, re.S).group(0)
    globals_ = re.findall(r'Header\.name">([^<]+)<', block)
    assert "User-Agent" in globals_ and "Accept-Language" in globals_   # shared → hoisted
    # User-Agent must not also be repeated on individual samplers
    assert x.count("<stringProp name=\"Header.name\">User-Agent</stringProp>") == 1


def test_launch_transaction_named():
    result = analyze((FIX / "sample_browser.har").read_bytes())
    assert result.transactions[0].name == "Launch Application"


def test_bearer_header_substituted_in_plan():
    x = _xml(FIX / "sample_bearer.har")
    assert "Bearer ${accessToken}" in x           # scheme-prefixed credential substituted
    assert "aaaa.bbbb.cccc" not in x              # the literal token never ships in the plan


def test_real_har_end_to_end_correlated_and_parameterized():
    har = EXAMPLES / "restful_booker.har"
    if not har.exists():
        return  # example capture not present in this checkout
    x = _xml(har)
    # correlations extracted, not hardcoded
    assert "Extract token (JSON)" in x and "Extract bookingid (JSON)" in x
    assert "${token}" in x and "${bookingid}" in x
    # the live token/booking id values must NOT appear as literals anywhere
    result = analyze(har.read_bytes())
    token = next(c.value for c in result.correlations if c.variable == "token")
    bid = next(c.value for c in result.correlations if c.variable == "bookingid")
    assert token not in x
    assert f"/booking/{bid}" not in x              # path uses ${bookingid}
    # parameters wired to CSV variables, not literal captured values
    assert "${firstname}" in x and "CSVDataSet" in x
    assert "Sally" not in x                         # firstname lives in the CSV, not the plan


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
