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


def test_plan_has_all_jmeter_constituents():
    # a complete, runnable plan: thread group (N users), defaults, cookie + header managers,
    # response assertion, think-time timer, transaction controllers, samplers.
    x = _xml(FIX / "sample_flow.har")
    for element in ("ThreadGroup", "HTTP Request Defaults", "HTTP Cookie Manager", "HTTP Header Manager",
                    "ResponseAssertion", "Assertion.response_code", "UniformRandomTimer",
                    "TransactionController", "HTTPSamplerProxy"):
        assert element in x, f"missing {element}"
    assert 'num_threads">${THREADS}' in x        # scales to N users


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


def test_env_portable_base_url_and_inherited_samplers():
    # the plan repoints via ${BASE_URL}: HTTP Request Defaults + primary-host samplers reference it,
    # so the same script runs against dev/stage/prod by editing one variable.
    x = _xml(FIX / "sample_flow.har")
    assert 'name="BASE_URL"' in x and 'name="PROTOCOL"' in x
    import re
    defaults = re.search(r'HTTP Request Defaults.*?HTTPSampler\.domain">([^<]*)', x, re.S).group(1)
    assert defaults == "${BASE_URL}"
    # primary-host samplers have empty domain (inherit the default) — no hardcoded host
    assert re.search(r'HTTPSampler\.domain"\s*/>', x) or 'HTTPSampler.domain"></stringProp>' in x


def test_steady_state_hold_enables_scheduler_zero_keeps_loop_count():
    r = analyze((FIX / "sample_flow.har").read_bytes())
    held = build_jmx_xml(r, {"threads": "100", "ramp": "30", "hold": "60"}).decode()
    assert 'ThreadGroup.scheduler">true' in held
    assert 'ThreadGroup.duration">${__intSum(${RAMP},${HOLD})}' in held
    assert 'LoopController.loops">-1' in held
    # default (no hold) stays loop-count driven — no behavior change
    plain = build_jmx_xml(r, {"threads": "100", "ramp": "30"}).decode()
    assert 'ThreadGroup.scheduler">false' in plain and 'LoopController.loops">${LOOPS}' in plain


def test_cache_and_dns_managers_present():
    x = _xml(FIX / "sample_flow.har")
    assert 'testclass="CacheManager"' in x and 'clearEachIteration">true' in x
    assert 'testclass="DNSCacheManager"' in x


def test_observed_think_time_default_from_capture():
    from har2jmx.emit.jmx import _observed_think_time
    r = analyze((FIX / "sample_flow.har").read_bytes())
    obs = _observed_think_time(r.capture)
    assert 100 <= obs <= 8000                          # clamped to a sane pacing range
    # with no think time supplied, the plan uses the observed value (not a flat 500 guess)
    x = build_jmx_xml(r, {"threads": "10"}).decode()
    import re
    assert re.search(r'name="THINKTIME".*?Argument\.value">' + str(obs) + '<', x, re.S)


def test_think_time_is_configurable_from_upload():
    # the uploaded "think time" value drives a THINKTIME variable the timer uses (like THREADS/RAMP),
    # so pacing is set at upload and stays editable in JMeter — not hardcoded.
    x = build_jmx_xml(analyze((FIX / "sample_flow.har").read_bytes()),
                      {"threads": "50", "loops": "1", "ramp": "10", "thinktime": "1500"}).decode()
    assert 'name="THINKTIME"' in x and ">1500<" in x
    assert 'ConstantTimer.delay">${THINKTIME}' in x
    assert 'RandomTimer.range">${THINKTIME}' in x
    # a default is supplied when the field is omitted
    d = build_jmx_xml(analyze((FIX / "sample_flow.har").read_bytes())).decode()
    assert 'name="THINKTIME"' in d and 'ConstantTimer.delay">${THINKTIME}' in d


def test_correlation_health_assertion_guards_false_greens():
    # every correlation extractor is paired with a variable-scoped assertion that fails the sample
    # when the extractor fell back to its NOT_FOUND sentinel — so a broken correlation (e.g. a login
    # that 200s with an error body) surfaces as a real failure, not a silent false-green.
    x = _xml(FIX / "sample_flow.har")
    assert 'testname="Assert orderId correlated"' in x
    assert "NOT_FOUND_orderId" in x
    assert 'name="Assertion.scope">variable' in x and 'name="Scope.variable">orderId' in x
    assert 'name="Assertion.test_type">20' in x           # Substring | Not → fails if sentinel present


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


def test_csv_row_synthesis_varies_safe_data_only():
    from har2jmx.emit.jmx import _synthesize_rows
    # safe business data (name/amount/date) is grown toward N rows, all distinct
    rows = _synthesize_rows(["firstname", "amount", "checkin"],
                            [("Sally", "100", "2026-01-01")], target=20)
    assert len(rows) == 20
    assert len(set(rows)) == 20                       # every synthesized row is distinct
    assert rows[0] == ("Sally", "100", "2026-01-01")  # observed row preserved first

    # credentials must never be fabricated (fake logins fail)
    assert _synthesize_rows(["username", "password"], [("admin", "pw123")], target=20) == [("admin", "pw123")]

    # coded real ids must never be fabricated (fake ids don't exist)
    assert _synthesize_rows(["productId"], [("PROD-8801",)], target=20) == [("PROD-8801",)]

    # a coded id alongside varyable data: id is cycled (kept real), the rest varies
    rows = _synthesize_rows(["payeeId", "amount"], [("PAYEE-55", "1200.00")], target=5)
    assert len(rows) == 5
    assert all(r[0] == "PAYEE-55" for r in rows)      # real payee preserved on every row
    assert len({r[1] for r in rows}) == 5             # amounts vary

    # a consolidated mixed row (credentials + a numeric id + safe fields): the id and credential are
    # cycled (never fabricated), only the safe field varies — so single-row merge doesn't freeze data.
    rows = _synthesize_rows(["customerId", "password", "amount"], [("7788123", "PIN9", "100")], target=4)
    assert len(rows) == 4
    assert all(r[0] == "7788123" for r in rows)       # numeric identity is real — cycled, not invented
    assert all(r[1] == "PIN9" for r in rows)          # credential never fabricated
    assert len({r[2] for r in rows}) == 4             # the safe amount still varies per user


def test_client_unique_key_uses_uuid_function():
    # a client-generated idempotency/request-id UUID must be fresh per request (${__UUID()}),
    # not a shared CSV value — else 100 users send the same key and the gateway dedups them.
    x = _xml(FIX / "sample_idempotency.har")
    assert "${__UUID()}" in x
    assert "8f14e45f-ceea-467a-9f3c-3a1b2c4d5e6f" not in x   # the recorded key never ships


def test_multipart_file_upload():
    har = EXAMPLES / "complex_upload.har"
    if not har.exists():
        return
    x = _xml(har)
    assert 'HTTPSampler.DO_MULTIPART_POST">true' in x   # real multipart upload
    assert "HTTPFileArg" in x and "File.paramname" in x
    assert "damage_front.jpg" in x                        # the uploaded file


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
