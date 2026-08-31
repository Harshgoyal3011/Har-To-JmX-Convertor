"""Milestone 12 (cutover) — JMX emitter.

Turns an ``EngineResult`` into a runnable JMeter test plan: an N-user Thread Group, HTTP defaults,
Cookie Manager, one CSV Data Set per parameter dataset, Transaction Controllers per user action, one
HTTP sampler per business request with correlated/parameterized values substituted (``${var}``), and
JSON/Regex extractors attached to the producing sampler for each correlation.

Substitution is whole-slot (a captured value is replaced only where it appears as a complete
path segment / query value / body field / header / cookie), reusing the M7 discipline.
"""

from __future__ import annotations

import csv as _csv
import json as _json
import re as _re
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from xml.dom import minidom
from xml.etree.ElementTree import Element, SubElement, tostring

from har2jmx.correlate import ExtractorType
from har2jmx.engine import EngineResult
from har2jmx.ir.normalized import BodyKind, NormalizedRequest
from har2jmx.patterns import GUID_RE, ID_FIELD_RE

# client-generated per-request keys — must be fresh each request, not a shared CSV value
_UNIQUE_KEY_RE = _re.compile(
    r"idempotenc|request.?id|correlation.?id|trace.?id|message.?id|nonce|"
    r"x-request|x-correlation|transaction.?id|requestid|correlationid",
    _re.IGNORECASE,
)


# ---------------------------------------------------------------- xml prop helpers

def _s(parent, name, value=""):
    el = SubElement(parent, "stringProp", {"name": name}); el.text = value; return el


def _b(parent, name, value):
    el = SubElement(parent, "boolProp", {"name": name}); el.text = "true" if value else "false"; return el


def _i(parent, name, value):
    el = SubElement(parent, "intProp", {"name": name}); el.text = str(value); return el


def _elem(parent, name, etype):
    return SubElement(parent, "elementProp", {"name": name, "elementType": etype})


def _coll(parent, name):
    return SubElement(parent, "collectionProp", {"name": name})


# ---------------------------------------------------------------- substitution

def _sub_ok(value: str) -> bool:
    # never blanket-replace short/ambiguous values (e.g. "1", "12") — they collide everywhere
    v = str(value)
    return len(v) >= 3 and v.lower() not in {"true", "false", "null", "none"}


def _cookie_manager_values(result: EngineResult) -> frozenset:
    """Session cookies replayed automatically by the Cookie Manager — no variable, no manual header."""
    return frozenset(c.value for c in result.correlations if c.extractor == ExtractorType.COOKIE_MANAGER)


def _generated_uuid_values(result: EngineResult) -> set[str]:
    """Client-generated GUIDs in idempotency/request/correlation keys — one per request at run time."""
    vals: set[str] = set()

    def scan(name: str, value: Any) -> None:
        if value and _UNIQUE_KEY_RE.search(name) and GUID_RE.match(str(value).strip()):
            vals.add(str(value).strip())

    def walk(obj: Any) -> None:
        if isinstance(obj, dict):
            for k, v in obj.items():
                scan(k, v) if not isinstance(v, (dict, list)) else walk(v)
        elif isinstance(obj, list):
            for it in obj:
                walk(it)

    for req in result.capture.requests:
        if req.classification.excluded:
            continue
        for n, v in req.request.headers:
            scan(n, v)
        for n, v in req.request.query:
            scan(n, v)
        for n, v in req.request.body.form:
            scan(n, v)
        if req.request.body.json is not None:
            walk(req.request.body.json)
    return vals


def _build_sub_map(result: EngineResult) -> dict[str, str]:
    sub: dict[str, str] = {}
    for c in result.correlations:                       # correlations win over parameters
        if c.extractor == ExtractorType.COOKIE_MANAGER:
            continue                                    # Cookie Manager replays it; no ${var}
        if _sub_ok(c.value):
            sub[str(c.value)] = f"${{{c.variable}}}"
    for uuid_val in _generated_uuid_values(result):     # fresh UUID per request (beats a CSV value)
        sub.setdefault(uuid_val, "${__UUID()}")
    for d in result.parameterization.datasets:
        for col in d.columns:
            for row in d.rows:
                v = row.get(col.name)
                if v not in (None, "") and _sub_ok(v):
                    sub.setdefault(str(v), f"${{{col.name}}}")
            if col.sample and _sub_ok(col.sample):
                sub.setdefault(str(col.sample), f"${{{col.name}}}")
    return sub


def _apply(value: Any, sub: dict[str, str]) -> str:
    return sub.get(str(value), str(value))


_SCHEME_RE = _re.compile(r"^(\s*\S+\s+)(\S.*)$")


def _apply_header(value: str, sub: dict[str, str]) -> str:
    """Whole-value substitution, plus scheme-prefixed credentials (e.g. 'Bearer <token>')."""
    s = str(value)
    if s in sub:
        return sub[s]
    m = _SCHEME_RE.match(s)
    if m and m.group(2).strip() in sub:
        return m.group(1) + sub[m.group(2).strip()]
    return s


def _sub_json(obj: Any, sub: dict[str, str]) -> Any:
    if isinstance(obj, dict):
        return {k: _sub_json(v, sub) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sub_json(v, sub) for v in obj]
    if isinstance(obj, bool) or obj is None:
        return obj
    if isinstance(obj, (str, int, float)):
        s = str(obj)
        return sub[s] if s in sub else obj
    return obj


def _sub_path(path: str, sub: dict[str, str]) -> str:
    parts = path.split("/")
    return "/".join(_apply(p, sub) if p else p for p in parts)


def _sub_raw(text: str, sub: dict[str, str]) -> str:
    """Substitute known correlated/parameter values inside a raw body (XML/SOAP/text).

    Values are significant (>=3 chars, guarded by _sub_ok); longest-first avoids partial overlaps.
    """
    for value in sorted(sub, key=len, reverse=True):
        if value in text:
            text = text.replace(value, sub[value])
    return text


# ---------------------------------------------------------------- samplers & extractors

def _add_http_sampler(parent_ht, req: NormalizedRequest, sub: dict[str, str], follow_redirects: bool = True,
                      global_headers: frozenset = frozenset(), cookie_mgr_values: frozenset = frozenset()) -> None:
    http = SubElement(parent_ht, "HTTPSamplerProxy", {
        "guiclass": "HttpTestSampleGui", "testclass": "HTTPSamplerProxy",
        "testname": f"{req.method} {_sub_path(req.request.path, sub)}",
        "enabled": "true",
    })
    args = _elem(http, "HTTPsampler.Arguments", "Arguments")
    coll = _coll(args, "Arguments.arguments")

    raw_body = ""
    if req.request.body.kind in {BodyKind.JSON, BodyKind.GRAPHQL} and req.request.body.json is not None:
        raw_body = _json.dumps(_sub_json(req.request.body.json, sub))
    elif req.request.body.kind in {BodyKind.XML, BodyKind.SOAP, BodyKind.TEXT} and req.request.body.raw:
        raw_body = _sub_raw(req.request.body.raw, sub)

    _b(http, "HTTPSampler.postBodyRaw", bool(raw_body))
    if raw_body:
        arg = _elem(coll, "", "HTTPArgument")
        _b(arg, "HTTPArgument.always_encode", False)
        _s(arg, "Argument.value", raw_body)
        _s(arg, "Argument.metadata", "=")
    else:
        for name, value in list(req.request.query) + list(req.request.body.form):
            arg = _elem(coll, name, "HTTPArgument")
            _b(arg, "HTTPArgument.always_encode", False)
            _s(arg, "Argument.name", name)
            _s(arg, "Argument.value", _apply(value, sub))
            _s(arg, "Argument.metadata", "=")
            _b(arg, "HTTPArgument.use_equals", True)

    _s(http, "HTTPSampler.domain", req.request.host)
    _s(http, "HTTPSampler.port", req.request.port)
    _s(http, "HTTPSampler.protocol", req.request.scheme)
    _s(http, "HTTPSampler.path", _sub_path(req.request.path, sub))
    _s(http, "HTTPSampler.method", req.method)
    _b(http, "HTTPSampler.follow_redirects", follow_redirects)
    _b(http, "HTTPSampler.use_keepalive", True)

    # multipart file upload — real file-upload elements, not empty form fields
    is_multipart = req.request.body.kind == BodyKind.MULTIPART
    _b(http, "HTTPSampler.DO_MULTIPART_POST", is_multipart)
    if req.request.body.files:
        files_el = _elem(http, "HTTPsampler.Files", "HTTPFileArgs")
        fcoll = _coll(files_el, "HTTPFileArgs.files")
        for param, filename, mimetype in req.request.body.files:
            fa = _elem(fcoll, filename, "HTTPFileArg")
            _s(fa, "File.path", filename)        # supply the local file at run time
            _s(fa, "File.paramname", param)
            _s(fa, "File.mimetype", mimetype)

    sampler_ht = SubElement(parent_ht, "hashTree")
    _add_header_manager(sampler_ht, req, sub, global_headers, cookie_mgr_values)


def _add_header_manager(parent_ht, req: NormalizedRequest, sub: dict[str, str],
                        global_headers: frozenset = frozenset(),
                        cookie_mgr_values: frozenset = frozenset()) -> None:
    # request-specific headers only — headers already carried by the global manager are skipped
    headers = [(n, v) for n, v in req.request.headers
               if n.lower() not in {"host", "content-length", "cookie"}
               and n.lower() not in global_headers and v]
    # cookies not replayed by the Cookie Manager are sent manually (substituted); session cookies
    # the Cookie Manager handles are omitted so we neither hardcode a stale value nor reference a
    # phantom variable.
    manual_cookies = [(n, v) for n, v in req.request.cookies if v not in cookie_mgr_values]
    if manual_cookies:
        cookie_val = "; ".join(f"{n}={_apply(v, sub)}" for n, v in manual_cookies)
        headers.append(("Cookie", cookie_val))
    if not headers:
        return
    mgr = SubElement(parent_ht, "HeaderManager", {
        "guiclass": "HeaderPanel", "testclass": "HeaderManager",
        "testname": "HTTP Header Manager", "enabled": "true"})
    coll = _coll(mgr, "HeaderManager.headers")
    for name, value in headers:
        h = _elem(coll, "", "Header")
        _s(h, "Header.name", name)
        _s(h, "Header.value", value if name == "Cookie" else _apply_header(value, sub))
    SubElement(parent_ht, "hashTree")


def _add_json_extractor(parent_ht, variable: str, expr: str) -> None:
    ex = SubElement(parent_ht, "JSONPostProcessor", {
        "guiclass": "JSONPostProcessorGui", "testclass": "JSONPostProcessor",
        "testname": f"Extract {variable} (JSON)", "enabled": "true"})
    _s(ex, "JSONPostProcessor.referenceNames", variable)
    _s(ex, "JSONPostProcessor.jsonPathExprs", expr)
    _s(ex, "JSONPostProcessor.match_numbers", "1")
    _s(ex, "JSONPostProcessor.defaultValues", f"NOT_FOUND_{variable}")
    SubElement(parent_ht, "hashTree")


def _add_regex_extractor(parent_ht, variable: str, expr: str, use_headers: bool) -> None:
    ex = SubElement(parent_ht, "RegexExtractor", {
        "guiclass": "RegexExtractorGui", "testclass": "RegexExtractor",
        "testname": f"Extract {variable} (Regex)", "enabled": "true"})
    _s(ex, "RegexExtractor.useHeaders", "true" if use_headers else "false")
    _s(ex, "RegexExtractor.refname", variable)
    _s(ex, "RegexExtractor.regex", expr)
    _s(ex, "RegexExtractor.template", "$1$")
    _s(ex, "RegexExtractor.default", f"NOT_FOUND_{variable}")
    _s(ex, "RegexExtractor.match_number", "1")
    SubElement(parent_ht, "hashTree")


# ---------------------------------------------------------------- config elements

def _add_test_plan(root_ht, name, config, comment: str = "Generated by har2jmx from a HAR capture."):
    tp = SubElement(root_ht, "TestPlan", {
        "guiclass": "TestPlanGui", "testclass": "TestPlan", "testname": name, "enabled": "true"})
    _s(tp, "TestPlan.comments", comment)
    _b(tp, "TestPlan.functional_mode", False)
    _b(tp, "TestPlan.serialize_threadgroups", False)
    args = _elem(tp, "TestPlan.user_defined_variables", "Arguments")
    coll = _coll(args, "Arguments.arguments")
    for var, val, desc in [("THREADS", config.get("threads", "10"), "Concurrent users"),
                           ("LOOPS", config.get("loops", "1"), "Iterations per user"),
                           ("RAMP", config.get("ramp", "5"), "Ramp-up seconds")]:
        a = _elem(coll, var, "Argument")
        _s(a, "Argument.name", var); _s(a, "Argument.value", val)
        _s(a, "Argument.metadata", "="); _s(a, "Argument.desc", desc)
    _s(tp, "TestPlan.user_define_classpath", "")
    return tp


def _add_thread_group(parent_ht):
    tg = SubElement(parent_ht, "ThreadGroup", {
        "guiclass": "ThreadGroupGui", "testclass": "ThreadGroup",
        "testname": "Users", "enabled": "true"})
    _s(tg, "ThreadGroup.on_sample_error", "continue")
    loop = _elem(tg, "ThreadGroup.main_controller", "LoopController")
    _b(loop, "LoopController.continue_forever", False)
    _s(loop, "LoopController.loops", "${LOOPS}")
    _s(tg, "ThreadGroup.num_threads", "${THREADS}")
    _s(tg, "ThreadGroup.ramp_time", "${RAMP}")
    _b(tg, "ThreadGroup.scheduler", False)


def _add_http_defaults(parent_ht, result: EngineResult):
    business = [r for r in result.capture.requests if not r.classification.excluded]
    hosts = Counter(r.request.host for r in business if r.request.host)
    if not hosts:
        return
    host, _ = hosts.most_common(1)[0]
    proto = next((r.request.scheme for r in business if r.request.host == host), "https")
    cfg = SubElement(parent_ht, "ConfigTestElement", {
        "guiclass": "HttpDefaultsGui", "testclass": "ConfigTestElement",
        "testname": "HTTP Request Defaults", "enabled": "true"})
    _elem(cfg, "HTTPsampler.Arguments", "Arguments")
    _s(cfg, "HTTPSampler.domain", host)
    _s(cfg, "HTTPSampler.protocol", proto)
    SubElement(parent_ht, "hashTree")


def _collect_common_headers(business: list[NormalizedRequest]) -> dict[str, tuple[str, str]]:
    """Headers shared (same name+value) across most business requests → hoisted to a global manager.

    Body-specific (Content-Type) and per-request/correlated (Authorization) headers stay per-sampler.
    """
    from collections import defaultdict
    values: dict[str, set] = defaultdict(set)
    present: dict[str, int] = defaultdict(int)
    orig: dict[str, str] = {}
    skip = {"host", "content-length", "cookie", "content-type", "authorization"}
    for req in business:
        seen: set[str] = set()
        for hn, hv in req.request.headers:
            low = hn.lower()
            if low in skip or not hv or low in seen:
                continue
            seen.add(low)
            values[low].add(hv)
            present[low] += 1
            orig[low] = hn
    n = len(business)
    threshold = max(2, round(n * 0.6))
    return {low: (orig[low], next(iter(vals)))
            for low, vals in values.items() if len(vals) == 1 and present[low] >= threshold}


def _add_global_header_manager(parent_ht, common: dict[str, tuple[str, str]], sub: dict[str, str]):
    mgr = SubElement(parent_ht, "HeaderManager", {
        "guiclass": "HeaderPanel", "testclass": "HeaderManager",
        "testname": "HTTP Header Manager", "enabled": "true"})
    coll = _coll(mgr, "HeaderManager.headers")
    for _low, (name, value) in sorted(common.items()):
        h = _elem(coll, "", "Header")
        _s(h, "Header.name", name)
        _s(h, "Header.value", _apply_header(value, sub))
    SubElement(parent_ht, "hashTree")


def _add_correlation_health_assertion(parent_ht, variable: str) -> None:
    """Fail the sample when a correlation didn't resolve, instead of sending garbage downstream.

    Every extractor falls back to the sentinel ``NOT_FOUND_<var>`` when it matches nothing — which
    happens when the app returned HTTP 200 with an error body (a failed login still 200s), so the
    response-code assertion passes while the flow is actually broken. This variable-scoped assertion
    marks the sample failed whenever the variable still holds its sentinel, turning that false-green
    into a real, visible failure. The sentinel never occurs in a healthy response, so it is
    false-positive-free.
    """
    a = SubElement(parent_ht, "ResponseAssertion", {
        "guiclass": "AssertionGui", "testclass": "ResponseAssertion",
        "testname": f"Assert {variable} correlated", "enabled": "true"})
    coll = _coll(a, "Asserion.test_strings")
    _s(coll, "assert_notfound", f"NOT_FOUND_{variable}")
    _s(a, "Assertion.scope", "variable")
    _s(a, "Scope.variable", variable)
    _s(a, "Assertion.test_field", "Assertion.response_data")
    _b(a, "Assertion.assume_success", False)
    _i(a, "Assertion.test_type", 20)   # 16 Substring | 4 Not  → fails if the sentinel is present
    SubElement(parent_ht, "hashTree")


def _add_response_assertion(parent_ht):
    """Thread-group scope: every sampler must return a 2xx/3xx code — surfaces failures under load."""
    a = SubElement(parent_ht, "ResponseAssertion", {
        "guiclass": "AssertionGui", "testclass": "ResponseAssertion",
        "testname": "Assert Response Code (2xx/3xx)", "enabled": "true"})
    coll = _coll(a, "Asserion.test_strings")
    _s(coll, "assert_pattern", r"^(2\d\d|3\d\d)$")
    _s(a, "Assertion.test_field", "Assertion.response_code")
    _b(a, "Assertion.assume_success", False)
    _i(a, "Assertion.test_type", 1)   # 1 = Matches (regex)
    SubElement(parent_ht, "hashTree")


def _add_think_time(parent_ht):
    """Thread-group scope: uniform random think time so 50 users don't hammer with zero pacing."""
    t = SubElement(parent_ht, "UniformRandomTimer", {
        "guiclass": "UniformRandomTimerGui", "testclass": "UniformRandomTimer",
        "testname": "Think Time", "enabled": "true"})
    _s(t, "ConstantTimer.delay", "500")
    _s(t, "RandomTimer.range", "1000")
    SubElement(parent_ht, "hashTree")


def _add_cookie_manager(parent_ht):
    mgr = SubElement(parent_ht, "CookieManager", {
        "guiclass": "CookiePanel", "testclass": "CookieManager",
        "testname": "HTTP Cookie Manager", "enabled": "true"})
    _coll(mgr, "CookieManager.cookies")
    _b(mgr, "CookieManager.clearEachIteration", True)
    _s(mgr, "CookieManager.policy", "standard")
    SubElement(parent_ht, "hashTree")


def _add_csv_dataset(parent_ht, dataset_name, filename, columns):
    cfg = SubElement(parent_ht, "CSVDataSet", {
        "guiclass": "TestBeanGUI", "testclass": "CSVDataSet",
        "testname": f"Test Data - {dataset_name}", "enabled": "true"})
    _s(cfg, "filename", filename)
    _s(cfg, "fileEncoding", "UTF-8")
    _s(cfg, "variableNames", ",".join(columns))
    _s(cfg, "delimiter", ",")
    _b(cfg, "quotedData", True)
    _b(cfg, "recycle", True)
    _b(cfg, "stopThread", False)
    _s(cfg, "shareMode", "shareMode.all")
    SubElement(parent_ht, "hashTree")


# ---------------------------------------------------------------- top level

def build_jmx_xml(result: EngineResult, config: dict[str, str] | None = None,
                  csv_files: dict[str, str] | None = None) -> bytes:
    config = config or {}
    csv_files = csv_files or {}
    sub = _build_sub_map(result)
    producer_map: dict[int, list] = {}
    for c in result.correlations:
        if c.extractor != ExtractorType.COOKIE_MANAGER:
            producer_map.setdefault(c.producer_index, []).append(c)

    root = Element("jmeterTestPlan", {"version": "1.2", "properties": "5.0", "jmeter": "5.6.3"})
    root_ht = SubElement(root, "hashTree")
    name = f"har2jmx Plan {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    manual = len(result.classification.needs_correlation())
    comment = ("Generated by har2jmx from a HAR capture."
               if not manual else
               f"⚠ {manual} value(s) need MANUAL correlation before running at load — see the "
               "*_manual_review.md file in this bundle. Generated by har2jmx from a HAR capture.")
    _add_test_plan(root_ht, name, config, comment)
    plan_ht = SubElement(root_ht, "hashTree")

    _add_thread_group(plan_ht)
    tg_ht = SubElement(plan_ht, "hashTree")

    cap = result.capture
    business = [r for r in cap.requests if not r.classification.excluded]
    common_headers = _collect_common_headers(business)
    global_header_names = frozenset(common_headers)
    cookie_mgr_values = _cookie_manager_values(result)

    _add_http_defaults(tg_ht, result)
    _add_cookie_manager(tg_ht)
    _add_global_header_manager(tg_ht, common_headers, sub)   # every plan gets an HTTP Header Manager
    _add_response_assertion(tg_ht)                            # validate responses under load
    _add_think_time(tg_ht)                                    # realistic pacing for N users
    for d in result.parameterization.datasets:
        fname = csv_files.get(d.name, f"{d.name.lower()}.csv")
        _add_csv_dataset(tg_ht, d.name, fname, [c.name for c in d.columns])

    for txn in result.transactions:
        biz = [i for i in txn.request_indices if not cap.requests[i].classification.excluded]
        if not biz:
            continue
        tc = SubElement(tg_ht, "TransactionController", {
            "guiclass": "TransactionControllerGui", "testclass": "TransactionController",
            "testname": txn.name, "enabled": "true"})
        _b(tc, "TransactionController.parent", True)
        _b(tc, "TransactionController.includeTimers", False)
        tc_ht = SubElement(tg_ht, "hashTree")
        for idx in biz:
            req = cap.requests[idx]
            produced = producer_map.get(idx, [])
            # if this request produces a value read from its redirect, it must not follow the redirect
            follow = not any(c.from_redirect for c in produced)
            _add_http_sampler(tc_ht, req, sub, follow_redirects=follow, global_headers=global_header_names,
                              cookie_mgr_values=cookie_mgr_values)
            # the sampler's own hashTree is the last child of tc_ht
            sampler_ht = list(tc_ht)[-1]
            for c in produced:
                if c.extractor == ExtractorType.JSON:
                    _add_json_extractor(sampler_ht, c.variable, c.expression)
                else:
                    use_headers = c.producer_location.startswith(("set-cookie:", "response.header:", "response.location:"))
                    _add_regex_extractor(sampler_ht, c.variable, c.expression, use_headers)
                # fail loudly if this correlation didn't resolve (false-green guard)
                _add_correlation_health_assertion(sampler_ht, c.variable)

    rough = tostring(root, encoding="utf-8")
    return minidom.parseString(rough).toprettyxml(indent="  ", encoding="utf-8")


# ---------------------------------------------------------------- CSV row synthesis

_MAX_CSV_ROWS = 200
_CRED_RE = _re.compile(r"user|pass|pwd|pin\b|otp|secret|token|login|credential|cvv|card", _re.IGNORECASE)
_CODED_ID_RE = _re.compile(r"^[A-Za-z]{2,}[-_][A-Za-z0-9][\w-]*$")
_EMAIL_RE = _re.compile(r"^([^@]+)@(.+)$")
_TRAIL_RE = _re.compile(r"^(.*?)(\d+)$")
_DATE_FORMATS = ("%Y-%m-%d", "%d-%m-%Y", "%m/%d/%Y", "%Y/%m/%d", "%d/%m/%Y",
                 "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.000Z", "%d-%b-%Y")


def _is_fixed_value_column(values: list[str]) -> bool:
    """Coded real ids / GUIDs must not be fabricated (fake ids don't exist in the system)."""
    non_empty = [v for v in values if v]
    return bool(non_empty) and all(GUID_RE.search(v) or _CODED_ID_RE.match(v) for v in non_empty)


def _vary(value: str, i: int) -> str:
    """Produce the i-th synthetic variant of a safe business value (date/number/email/text)."""
    if i == 0 or not value:
        return value
    v = str(value)
    for fmt in _DATE_FORMATS:
        try:
            return (datetime.strptime(v, fmt) + timedelta(days=i)).strftime(fmt)
        except ValueError:
            continue
    if v.lstrip("-").isdigit():
        return str(int(v) + i)
    try:
        if "." in v:
            return f"{float(v) + i:.2f}"
    except ValueError:
        pass
    m = _EMAIL_RE.match(v)
    if m:
        local, domain = m.group(1), m.group(2)
        tm = _TRAIL_RE.match(local)
        local = f"{tm.group(1)}{int(tm.group(2)) + i}" if tm else f"{local}{i}"
        return f"{local}@{domain}"
    tm = _TRAIL_RE.match(v)
    if tm:
        return f"{tm.group(1)}{int(tm.group(2)) + i}"
    return f"{v}{i + 1}"


def _synthesize_rows(cols: list[str], observed: list[tuple], target: int) -> list[tuple]:
    """Grow a dataset toward `target` rows by varying safe columns; credential datasets and coded-id
    columns are never fabricated (cycled from observed instead)."""
    if not observed or len(observed) >= target:
        return observed
    col_values = {i: [o[i] for o in observed] for i in range(len(cols))}
    # a column is fixed (cycled from observed, never fabricated) if it is a credential or a coded id;
    # only genuinely safe columns are varied. This lets a mixed dataset (credentials + coded ids +
    # safe fields, as produced by single-row consolidation) still vary its safe fields per user while
    # keeping every credential/id real — instead of freezing the whole file at one row.
    def _fixed(i: int) -> bool:
        # credentials, coded ids, and any id-named column are real values that must not be fabricated
        # (a synthesized customerId/accountId would be an identity that doesn't exist) — cycle them.
        return (bool(_CRED_RE.search(cols[i])) or bool(ID_FIELD_RE.search(cols[i]))
                or _is_fixed_value_column(col_values[i]))

    varyable = [i for i in range(len(cols)) if not _fixed(i)]
    if not varyable:                                  # nothing safe to vary (all creds/coded ids) — keep
        return observed
    out = list(observed)
    seen = set(observed)
    base = observed[0]
    idx = len(observed)
    guard = 0
    while len(out) < target and guard < target * 4:
        guard += 1
        row = tuple(_vary(base[i], idx) if i in varyable else observed[idx % len(observed)][i]
                    for i in range(len(cols)))
        if row not in seen:
            seen.add(row)
            out.append(row)
        idx += 1
    return out


def _manual_review_markdown(result: EngineResult, jmx_name: str) -> str | None:
    """Readable checklist of values the engine could not auto-correlate; None when there are none."""
    from har2jmx.webreport import build_manual_correlations
    items = build_manual_correlations(result)
    if not items:
        return None
    lines = [
        "# Manual Correlation Needed",
        "",
        f"**Plan:** {jmx_name}.jmx",
        f"**{len(items)} value(s)** are sent in requests but could not be automatically correlated.",
        "Left as-is they ship as hardcoded literals and will fail at load (every virtual user reuses one",
        "recorded value). Wire each one up before running at scale.",
        "",
    ]
    for i, it in enumerate(items, 1):
        lines += [
            f"## {i}. `{it['field']}`  (value `{it['value']}`)",
            "",
            f"- **Why:** {it['reason']}",
            f"- **Used in:** {'; '.join(it['usedIn']) or '(a later request)'}",
            f"- **Fix:** {it['suggestion']}",
            "",
        ]
    return "\n".join(lines)


def emit_jmx(result: EngineResult, out_dir: str | Path, config: dict[str, str] | None = None,
             name: str = "test_plan") -> tuple[Path, list[Path], list[Path]]:
    """Write the .jmx, its CSV files, and (when needed) a manual-review report to out_dir.
    Returns (jmx_path, [csv_paths], [report_paths])."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    config = config or {}
    try:
        target = min(max(int(str(config.get("threads", "10")).strip()), 1), _MAX_CSV_ROWS)
    except (TypeError, ValueError):
        target = 10
    csv_files: dict[str, str] = {}
    csv_paths: list[Path] = []
    for d in result.parameterization.datasets:
        fname = f"{name}_{d.name.lower()}.csv"
        csv_files[d.name] = fname
        path = out / fname
        cols = [c.name for c in d.columns]
        observed: list[tuple] = []
        seen: set[tuple] = set()
        for row in d.rows:                               # unique observed rows
            cells = tuple(str(row.get(c, "")) for c in cols)
            if cells not in seen:
                seen.add(cells)
                observed.append(cells)
        rows = _synthesize_rows(cols, observed, target)  # grow safe data toward N users
        with path.open("w", newline="", encoding="utf-8") as fh:
            w = _csv.writer(fh)
            w.writerow(cols)
            w.writerows(rows)
        csv_paths.append(path)

    xml = build_jmx_xml(result, config, csv_files)
    jmx_path = out / f"{name}.jmx"
    jmx_path.write_bytes(xml)

    report_paths: list[Path] = []
    review_md = _manual_review_markdown(result, name)
    if review_md:
        review_path = out / f"{name}_manual_review.md"
        review_path.write_text(review_md, encoding="utf-8")
        report_paths.append(review_path)

    return jmx_path, csv_paths, report_paths
