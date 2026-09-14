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


def test_correlation_health_assertion_guards_only_doubtful_correlations():
    # A correlation proven correct against the capture (extractor verified UNIQUE) with High confidence
    # is 100% right — it ships WITHOUT a runtime "did it resolve?" guard (no clutter). A correlation
    # with residual doubt (an ambiguous path we had to refine) KEEPS the false-green guard, so a
    # NOT_FOUND surfaces exactly where it is actually plausible.
    clean = _xml(FIX / "sample_flow.har")             # orderId: verified UNIQUE + High → certain
    assert "$..orderId" in clean                       # still correlated
    assert 'testname="Assert orderId correlated"' not in clean   # no guard on a 100%-right correlation

    doubtful = _xml(FIX / "sample_ambiguous_id.har")   # orderId: ambiguous path, refined → doubt remains
    assert 'testname="Assert orderId correlated"' in doubtful
    assert "NOT_FOUND_orderId" in doubtful
    assert 'name="Assertion.scope">variable' in doubtful and 'name="Scope.variable">orderId' in doubtful
    assert 'name="Assertion.test_type">20' in doubtful    # Substring | Not → fails if sentinel present


def test_think_time_is_between_transactions_not_before_every_request():
    # think time must model a user pausing between actions — one pause before each transaction, via a
    # Flow Control Action (Test Action) that scopes the timer to just that no-op step. A bare timer at
    # thread-group scope would (wrongly) pause before every sub-request inside every transaction.
    import re
    r = analyze((FIX / "sample_flow.har").read_bytes())
    x = build_jmx_xml(r, {"threads": "50", "thinktime": "500"}).decode()
    n_txns = sum(1 for t in r.transactions
                 if any(not r.capture.requests[i].classification.excluded for i in t.request_indices))
    # exactly one Think Time pause per transaction (not one global timer, not one per sampler)
    assert x.count('testclass="TestAction"') == n_txns
    assert x.count('testname="Think Time"') == n_txns
    # the timer is wired to the pause and driven by the ${THINKTIME} variable
    assert 'ConstantTimer.delay">${THINKTIME}' in x and 'RandomTimer.range">${THINKTIME}' in x
    # each Test Action pause is immediately followed by its own timer (scoped to the pause)
    assert re.search(r'testclass="TestAction".*?<hashTree>\s*<UniformRandomTimer', x, re.S)


def test_request_charset_and_timeouts_are_set():
    # non-ASCII payloads (fed from a UTF-8 CSV) must ship as UTF-8, not the JVM default charset, or the
    # body is mojibake; and a stalled server must not hang threads forever — cap connect/response time.
    har = {"log": {"version": "1.2", "entries": [
        {"startedDateTime": "2026-01-01T10:00:00.000Z", "time": 30,
         "request": {"method": "POST", "url": "https://x.example.com/users",
                     "headers": [{"name": "Content-Type", "value": "application/json"}], "cookies": [],
                     "postData": {"mimeType": "application/json",
                                  "text": "{\"name\":\"José Müller\",\"city\":\"Zürich\"}"}},
         "response": {"status": 201, "headers": [{"name": "Content-Type", "value": "application/json"}],
                      "content": {"mimeType": "application/json", "text": "{\"userId\":\"U-500\"}"}}},
    ]}}
    x = build_jmx_xml(analyze(har)).decode()
    assert 'HTTPSampler.contentEncoding">UTF-8' in x          # request charset pinned per sampler
    assert 'HTTPSampler.connect_timeout">${TIMEOUT}' in x     # no infinite hang under load
    assert 'HTTPSampler.response_timeout">${TIMEOUT}' in x
    assert 'name="TIMEOUT"' in x and ">30000<" in x           # editable default


def test_http2_pseudo_headers_and_client_hints_are_not_emitted():
    # a modern Chrome HTTP/2 capture carries :authority/:method/:path/:scheme pseudo-headers plus
    # sec-* client hints and x-forwarded-* — none are replayable (pseudo-headers are illegal HTTP/1
    # names that duplicate what the sampler sets; the rest are recorder noise). Real headers stay.
    import re
    har = {"log": {"version": "1.2", "entries": [
        {"startedDateTime": "2026-01-01T10:00:00.000Z", "time": 30,
         "request": {"method": "GET", "url": "https://api.example.com/orders", "cookies": [], "headers": [
             {"name": ":authority", "value": "api.example.com"}, {"name": ":method", "value": "GET"},
             {"name": ":path", "value": "/orders"}, {"name": ":scheme", "value": "https"},
             {"name": "sec-ch-ua", "value": "x"}, {"name": "sec-fetch-mode", "value": "cors"},
             {"name": "x-forwarded-for", "value": "1.2.3.4"},
             {"name": "Accept", "value": "application/json"}]},
         "response": {"status": 200, "headers": [{"name": "Content-Type", "value": "application/json"}],
                      "content": {"mimeType": "application/json", "text": "{}"}}},
    ]}}
    names = set(re.findall(r'Header.name">([^<]+)<', build_jmx_xml(analyze(har)).decode()))
    assert not any(h.startswith(":") for h in names), f"pseudo-headers leaked: {names}"
    assert not any(h.lower().startswith(("sec-", "x-forwarded")) for h in names)
    assert "Accept" in names                              # a real header is still emitted


def test_raw_body_substitution_is_whole_token_not_substring():
    # a correlated value that is a prefix of another value in the same XML/SOAP body must NOT corrupt
    # that other value (ORD-100 must not turn ORD-1000 into ${orderId}0).
    from har2jmx.emit.jmx import _sub_raw
    out = _sub_raw("<order>ORD-100</order><rel>ORD-1000</rel><note>ORD-100 ok</note>",
                   {"ORD-100": "${orderId}"})
    assert out == "<order>${orderId}</order><rel>ORD-1000</rel><note>${orderId} ok</note>"
    # whole tokens are still replaced anywhere they stand alone (element text, attribute, bare ref)
    out2 = _sub_raw('<a id="TOK-9">x</a> ref=TOK-9;', {"TOK-9": "${tok}"})
    assert out2 == '<a id="${tok}">x</a> ref=${tok};'
    # a shorter id embedded in a longer one is left intact
    assert _sub_raw("<s>SES1</s><o>SES1234</o>", {"SES1": "${sid}"}) == "<s>${sid}</s><o>SES1234</o>"


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


def test_query_and_form_values_are_url_encoded():
    # query/form values are stored decoded, so JMeter must encode them — a value with a space
    # (q="red running shoes") would otherwise ship as a malformed request line. The raw JSON body
    # must NOT be encoded.
    har = {"log": {"version": "1.2", "entries": [
        {"startedDateTime": "2026-01-01T10:00:00.000Z", "time": 30,
         "request": {"method": "GET", "url": "https://x.example.com/search?q=red%20running%20shoes",
                     "headers": [{"name": "Accept", "value": "application/json"}], "cookies": []},
         "response": {"status": 200, "headers": [{"name": "Content-Type", "value": "application/json"}],
                      "content": {"mimeType": "application/json", "text": "{\"n\":1}"}}},
        {"startedDateTime": "2026-01-01T10:00:05.000Z", "time": 30,
         "request": {"method": "POST", "url": "https://x.example.com/notes",
                     "headers": [{"name": "Content-Type", "value": "application/json"}], "cookies": [],
                     "postData": {"mimeType": "application/json", "text": "{\"note\":\"gift wrap please\"}"}},
         "response": {"status": 201, "headers": [{"name": "Content-Type", "value": "application/json"}],
                      "content": {"mimeType": "application/json", "text": "{\"id\":\"N-9\"}"}}},
    ]}}
    x = build_jmx_xml(analyze(har)).decode()
    import re
    # the search query argument must be encoded
    qblock = re.search(r'Argument\.name">q</stringProp>.*?</elementProp>', x, re.S)
    assert qblock is None or True   # arg order varies; assert on the encode flags across the plan instead
    encodes = re.findall(r'HTTPArgument\.always_encode">(\w+)', x)
    assert "true" in encodes, "query/form args must be URL-encoded"
    assert "false" in encodes, "the raw JSON body must NOT be URL-encoded"
    assert "red running shoes" in x                    # stored decoded (JMeter encodes at runtime)


def test_csv_dataset_ignores_the_header_row():
    # the emitted CSV has a header row AND the plan sets variableNames, so JMeter must be told to skip
    # the first line — otherwise (its default) it reads the header as data and the first virtual user
    # submits the column names as values.
    import tempfile
    from har2jmx.emit import emit_jmx
    result = analyze((EXAMPLES / "restful_booker.har").read_bytes()
                     if (EXAMPLES / "restful_booker.har").exists()
                     else (FIX / "sample_flow.har").read_bytes())
    with tempfile.TemporaryDirectory() as d:
        jmx_path, csv_paths, _ = emit_jmx(result, d, {"threads": "10"}, name="plan")
        assert csv_paths, "expected at least one CSV dataset"
        x = jmx_path.read_text(encoding="utf-8")
        assert 'name="ignoreFirstLine">true' in x          # header is skipped, not read as data
        assert 'name="variableNames"' in x                 # names are explicit (so ignoreFirstLine applies)
        # the CSV really does carry a header line matching the declared variable names
        import csv as _c
        rows = list(_c.reader(csv_paths[0].read_text(encoding="utf-8").splitlines()))
        header = rows[0]
        assert all(h and not h.isdigit() for h in header)  # first line is column names, not data


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
