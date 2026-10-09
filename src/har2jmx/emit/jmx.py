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
from urllib.parse import parse_qsl, quote_plus, unquote, urlsplit
from xml.dom import minidom
from xml.etree.ElementTree import Element, SubElement, tostring

from har2jmx.correlate import ExtractorType
from har2jmx.correlate.cookies import cookie_value_expression
from har2jmx.emit.authentication import (
    add_cookie_normalization,
    add_runtime_checks,
    auth_representations,
    authentication_dependency,
    cookie_decoding_required,
)
from har2jmx.emit.bindings import VariableBindings
from har2jmx.emit.redirects import add_location_capture, location_variable, redirect_execution
from har2jmx.engine import EngineResult
from har2jmx.ir.normalized import BodyKind, NormalizedRequest
from har2jmx.parameterize.context import credential_kind, field_key
from har2jmx.patterns import GUID_RE, ID_FIELD_RE
from har2jmx.validate import ExtractorStatus

# Headers JMeter must not replay. HTTP/2 pseudo-headers (:authority/:method/:path/:scheme) are illegal
# HTTP/1 header names and duplicate what the sampler already sets — emitting them breaks the request.
# Browser client-hints (sec-ch-*, sec-fetch-*) and forwarding headers (x-forwarded-*) are recorder
# noise, not part of the API contract. Mirrors the pseudo-header filter the lineage layer already uses.
_NON_REPLAYABLE_HEADER_PREFIXES = (":", "sec-", "x-forwarded")


def _replayable_header(name: str) -> bool:
    return not name.lower().startswith(_NON_REPLAYABLE_HEADER_PREFIXES)


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
    # never blanket-replace short/ambiguous values (e.g. "1", "12") — they collide everywhere.
    # Short numerics are substituted only via slot_subs (exact query/path/body slot).
    v = str(value)
    return len(v) >= 3 and v.lower() not in {"true", "false", "null", "none"}


def _param_slot_subs(result: EngineResult, request_index: int | None = None,
                     bindings: VariableBindings | None = None) -> list[tuple[str, str, frozenset]]:
    """(value, csv_column, request locations) for slot-exact substitution."""
    out: list[tuple[str, str, frozenset]] = []
    bindings = bindings if bindings is not None else VariableBindings(result)
    for d in result.parameterization.datasets:
        for col in d.columns:
            slots = [s for s in col.slots if getattr(s, "side", "request") == "request"
                     and (request_index is None or s.request_index == request_index)]
            own = [s for s in slots if field_key(s.field) == field_key(col.logical_field or col.name)
                   or field_key(s.field) == field_key(col.name)]
            if credential_kind(col.logical_field) == "identity":
                own = [s for s in slots if credential_kind(s.field) == "identity"]
            # Distinct fields with equal samples retain distinct bindings;
            # entity identities may deliberately span differently named slots.
            if col.entity_field is None and own:
                slots = own
            if not slots:
                continue
            locs = frozenset(s.location for s in slots)
            vals = {str(col.sample or ""), str(col.original or ""), str(col.normalized or "")}
            # HAR form params can contain an encoded spelling while lineage and
            # the CSV use its decoded logical value. Match the recorded spelling
            # only in the approved parameter slots; JMeter encodes the CSV value.
            vals.update(s.original for s in slots if s.original)
            for row in d.rows:
                v = row.get(col.name)
                if v not in (None, ""):
                    vals.add(str(v))
            for v in vals:
                if v:
                    out.append((v, bindings.parameter_name(d, col), locs))
    return out


def _slot_apply(value: Any, slot_key: str, slot_subs: list, sub: dict[str, str]) -> str:
    """Replace ``value`` only when this exact request slot is a parameterized column."""
    s = str(value)
    for raw, var, locs in slot_subs:
        if raw != s:
            continue
        if slot_key in locs:
            return f"${{{var}}}"
        if slot_key.startswith("request.path") and any(l.startswith("request.path") for l in locs):
            return f"${{{var}}}"
        if slot_key.startswith("request.body:") and any(
            l == slot_key or l == "request.body:variables." + slot_key.split(":", 1)[1] for l in locs
        ):
            return f"${{{var}}}"
    return sub.get(s, s)


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
    # Preserve the existing review policy for unresolved non-auth values. Accepted
    # auth dependencies always use runtime vars and fail closed at their producer;
    # an extraction failure must never fall back to a captured authentication value.
    unresolved = {chk.value for chk in result.extractor_checks if not chk.ok}
    for c in result.correlations:                       # correlations win over parameters
        if c.extractor == ExtractorType.COOKIE_MANAGER:
            continue                                    # Cookie Manager replays it; no ${var}
        auth_state = authentication_dependency(result, c)
        if c.value in unresolved and not auth_state:
            continue                                    # no verified extractor → keep the literal
        if _sub_ok(c.value) or auth_state:
            sub[str(c.value)] = f"${{{c.variable}}}"
            if auth_state:
                for raw in auth_representations(result, c):
                    sub[raw] = f"${{__urlencode(${{{c.variable}}})}}"
    for uuid_val in _generated_uuid_values(result):     # fresh UUID per request (beats a CSV value)
        sub.setdefault(uuid_val, "${__UUID()}")
    # CSV substitutions are applied only through approved request slots. The
    # existing correlation/UUID map above retains its discovery and matching.
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


def _sub_json(obj: Any, sub: dict[str, str], slot_subs: list | None = None, prefix: str = "") -> Any:
    slot_subs = slot_subs or []
    if isinstance(obj, dict):
        return {
            k: _sub_json(v, sub, slot_subs, f"{prefix}.{k}" if prefix else str(k))
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [_sub_json(v, sub, slot_subs, prefix) for v in obj]
    if isinstance(obj, bool) or obj is None:
        return obj
    if isinstance(obj, (str, int, float)):
        applied = _slot_apply(obj, f"request.body:{prefix}", slot_subs, sub)
        if applied != str(obj):
            return applied
        s = str(obj)
        return sub[s] if s in sub else obj
    return obj


_PATH_FILE_EXT_RE = _re.compile(r"\.(?:json|php|xml|html?|aspx|jsp|cgi)$", _re.IGNORECASE)


def _sub_path(path: str, sub: dict[str, str], slot_subs: list | None = None) -> str:
    slot_subs = slot_subs or []
    for raw, var, locs in sorted(slot_subs, key=lambda t: len(t[0]), reverse=True):
        if "/" not in raw:
            continue
        if not any(l.startswith("request.path") for l in locs):
            continue
        if raw in path:
            path = path.replace(raw, f"${{{var}}}", 1)
    parts = path.split("/")
    out: list[str] = []
    for p in parts:
        if not p or p.startswith("${"):
            out.append(p)
            continue
        applied = _slot_apply(p, "request.path", slot_subs, sub)
        if applied == p:
            stem = _PATH_FILE_EXT_RE.sub("", p) if _PATH_FILE_EXT_RE.search(p) else p
            if stem != p:
                slotted = _slot_apply(stem, "request.path", slot_subs, sub)
                if slotted != stem:
                    applied = slotted + p[len(stem):]
        out.append(applied)
    return "/".join(out)


def _sub_raw(text: str, sub: dict[str, str]) -> str:
    """Substitute known correlated/parameter values inside a raw body (XML/SOAP/text).

    Whole-token only: a plain str.replace() would corrupt a *different* value that merely shares a
    prefix (ORD-100 turning ORD-1000 into ${orderId}0, SES1 turning SES1234 into ${sid}234). Match the
    value only when it is not embedded in a longer identifier — bounded by a non-[word/-] character on
    each side — mirroring the whole-slot discipline used everywhere else in the pipeline. Longest-first
    still prevents a shorter value from pre-empting a longer overlapping one.
    """
    for value in sorted(sub, key=len, reverse=True):
        if value not in text:
            continue
        pat = _re.compile(r"(?<![\w-])" + _re.escape(value) + r"(?![\w-])")
        text = pat.sub(lambda _m, v=value: sub[v], text)
    return text


# ---------------------------------------------------------------- samplers & extractors

def _encoded_form_bindings(result: EngineResult, request_index: int,
                           sub: dict[str, str]) -> list[tuple[str, str, frozenset]]:
    """Bind known percent-encoded forms of already accepted dependencies locally.

    HAR params can retain percent escapes even when lineage uses decoded values.
    HTTPArgument encodes its resolved value, so bind the canonical variable directly.
    Do not add encoded aliases to the global literal map or discover new edges.
    """
    request = result.capture.requests[request_index].request
    if request.body.kind != BodyKind.FORM:
        return []
    checks = {check.variable: check for check in result.extractor_checks}
    owners: dict[tuple[str, str], set[str]] = {}
    for correlation in result.correlations:
        check = checks.get(correlation.variable)
        if (request_index not in correlation.consumers
                or correlation.producer_index >= request_index
                or correlation.extractor == ExtractorType.COOKIE_MANAGER
                or (check is not None and not check.ok)
                or sub.get(correlation.value) != f"${{{correlation.variable}}}"):
            continue
        for name, raw in request.body.form:
            if "%" in raw and raw != correlation.value and unquote(raw) == correlation.value:
                owners.setdefault((name, raw), set()).add(correlation.variable)
    return [(raw, next(iter(variables)), frozenset({f"request.body:{name}"}))
            for (name, raw), variables in owners.items() if len(variables) == 1]


def _request_path(req: NormalizedRequest, sub: dict[str, str], slot_subs: list) -> str:
    """Build the URL independently of the body, using authoritative IR pairs.

    Retain captured query spelling only when its decoded pairs agree with IR.
    Substituted values need the runtime encoding formerly supplied by HTTPArgument.
    """
    path = _sub_path(req.request.path, sub, slot_subs)
    pairs = req.request.query
    original = urlsplit(req.request.url).query
    if parse_qsl(original, keep_blank_values=True) == pairs:
        tokens = original.split("&") if original else []
    else:
        tokens = [f"{quote_plus(str(n))}={quote_plus(str(v))}" for n, v in pairs]
    query = []
    pair_index = 0
    for token in tokens:
        if not token:  # parse_qsl ignores empty separators; retain their spelling
            query.append(token)
            continue
        name, value = pairs[pair_index]
        pair_index += 1
        applied = _slot_apply(value, f"request.query:{name}", slot_subs, sub)
        if applied != str(value):
            encoded_name = token.partition("=")[0]
            token = f"{encoded_name}=${{__urlencode({applied})}}"
        query.append(token)
    return path + ("?" + "&".join(query) if tokens else "")


def _add_http_sampler(parent_ht, req: NormalizedRequest, sub: dict[str, str], follow_redirects: bool = True,
                      global_headers: frozenset = frozenset(), cookie_mgr_values: frozenset = frozenset(),
                      primary_host: str = "", slot_subs: list | None = None,
                      redirect_target: str = "", encoded_form_bindings: list | None = None) -> None:
    slot_subs = slot_subs or []
    http = SubElement(parent_ht, "HTTPSamplerProxy", {
        "guiclass": "HttpTestSampleGui", "testclass": "HTTPSamplerProxy",
        "testname": f"{req.method} {redirect_target or _sub_path(req.request.path, sub, slot_subs)}",
        "enabled": "true",
    })
    args = _elem(http, "HTTPsampler.Arguments", "Arguments")
    coll = _coll(args, "Arguments.arguments")

    raw_body = ""
    if req.request.body.kind in {BodyKind.JSON, BodyKind.GRAPHQL} and req.request.body.json is not None:
        js = req.request.body.json
        if req.request.body.kind == BodyKind.GRAPHQL and isinstance(js, dict) and "variables" in js:
            js = dict(js)
            js["variables"] = _sub_json(js.get("variables") or {}, sub, slot_subs, "")
            raw_body = _json.dumps(js)
        else:
            raw_body = _json.dumps(_sub_json(js, sub, slot_subs))
    elif req.request.body.kind in {BodyKind.XML, BodyKind.SOAP, BodyKind.TEXT} and req.request.body.raw:
        # XML parameter slots are scoped to this request; correlation continues
        # to use the existing whole-token substitution behavior unchanged.
        body_sub = dict(sub)
        for raw, var, locs in slot_subs:
            if any(l.startswith("request.xml:") for l in locs):
                body_sub.setdefault(raw, f"${{{var}}}")
        raw_body = _sub_raw(req.request.body.raw, body_sub)

    _b(http, "HTTPSampler.postBodyRaw", bool(raw_body))
    if raw_body:
        arg = _elem(coll, "", "HTTPArgument")
        _b(arg, "HTTPArgument.always_encode", False)
        _s(arg, "Argument.value", raw_body)
        _s(arg, "Argument.metadata", "=")
    else:
        args_list = [(n, v, f"request.body:{n}") for n, v in req.request.body.form]
        for name, value, slot_key in args_list:
            arg = _elem(coll, name, "HTTPArgument")
            # Form values are stored DECODED (parse_qsl), so JMeter must URL-encode them or a value
            # with a space/&/+/= (e.g. q="red running shoes") ships as a malformed request line. Encoding
            # a ${var} encodes its RESOLVED value, so correlations/parameters stay correct. (The raw
            # JSON/XML body above keeps always_encode=false — a body blob must not be URL-encoded.)
            _b(arg, "HTTPArgument.always_encode", True)
            _s(arg, "Argument.name", name)
            _s(arg, "Argument.value", _slot_apply(value, slot_key,
               slot_subs + (encoded_form_bindings or []), sub))
            _s(arg, "Argument.metadata", "=")
            _b(arg, "HTTPArgument.use_equals", True)

    # On the primary host, leave domain/protocol empty so the sampler inherits ${BASE_URL}/${PROTOCOL}
    # from HTTP Request Defaults (env-portable). Secondary hosts (multi-domain captures) stay explicit.
    on_primary = bool(primary_host) and req.request.host == primary_host
    _s(http, "HTTPSampler.domain", "" if on_primary else req.request.host)
    _s(http, "HTTPSampler.port", req.request.port)
    _s(http, "HTTPSampler.protocol", "" if on_primary else req.request.scheme)
    # A redirect's Location owns its complete URL, including its query.
    _s(http, "HTTPSampler.path", redirect_target or _request_path(req, sub, slot_subs))
    _s(http, "HTTPSampler.method", req.method)
    _b(http, "HTTPSampler.follow_redirects", follow_redirects)
    _b(http, "HTTPSampler.use_keepalive", True)
    # Pin the charset. Without it JMeter encodes the body/params with the JVM default charset at run
    # time, so non-ASCII data (accented names, non-Latin scripts — often fed from a UTF-8 CSV) ships as
    # mojibake and the server rejects or stores garbage. UTF-8 is the correct modern default.
    _s(http, "HTTPSampler.contentEncoding", "UTF-8")

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
    _add_header_manager(sampler_ht, req, sub, global_headers, cookie_mgr_values, slot_subs)


def _add_header_manager(parent_ht, req: NormalizedRequest, sub: dict[str, str],
                        global_headers: frozenset = frozenset(),
                        cookie_mgr_values: frozenset = frozenset(),
                        slot_subs: list | None = None) -> None:
    slot_subs = slot_subs or []
    # request-specific headers only — headers already carried by the global manager are skipped, and
    # non-replayable ones (HTTP/2 pseudo-headers, client-hints, forwarding) are dropped entirely.
    headers = [(n, v) for n, v in req.request.headers
               if n.lower() not in {"host", "content-length", "cookie"}
               and n.lower() not in global_headers and v and _replayable_header(n)]
    # A raw body must carry a Content-Type. Some captures record the JSON/XML body but not the header
    # (fetch() defaults, tool quirks); JMeter would then POST the raw payload with no Content-Type and
    # the server 415s / can't parse it. Supply it from the body's known media type when it's missing.
    _RAW_KINDS = {BodyKind.JSON, BodyKind.GRAPHQL, BodyKind.XML, BodyKind.SOAP, BodyKind.TEXT}
    if (req.request.body.kind in _RAW_KINDS and req.request.body.mime
            and not any(n.lower() == "content-type" for n, _ in req.request.headers)):
        headers.append(("Content-Type", req.request.body.mime))
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
        if name == "Cookie":
            hdr_val = value
        else:
            slotted = _slot_apply(value, f"request.header:{name}", slot_subs, {})
            hdr_val = slotted if slotted != str(value) else _apply_header(value, sub)
        _s(h, "Header.value", hdr_val)
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

def _add_test_plan(root_ht, name, config, comment: str = "Generated by har2jmx from a HAR capture.",
                   base_url: str = "", protocol: str = "https"):
    tp = SubElement(root_ht, "TestPlan", {
        "guiclass": "TestPlanGui", "testclass": "TestPlan", "testname": name, "enabled": "true"})
    _s(tp, "TestPlan.comments", comment)
    _b(tp, "TestPlan.functional_mode", False)
    _b(tp, "TestPlan.serialize_threadgroups", False)
    args = _elem(tp, "TestPlan.user_defined_variables", "Arguments")
    coll = _coll(args, "Arguments.arguments")
    for var, val, desc in [("BASE_URL", base_url, "Target host — edit to repoint at dev/stage/prod"),
                           ("PROTOCOL", protocol, "http or https"),
                           ("THREADS", config.get("threads", "10"), "Concurrent users"),
                           ("LOOPS", config.get("loops", "1"), "Iterations per user (ignored when HOLD>0)"),
                           ("RAMP", config.get("ramp", "5"), "Ramp-up seconds"),
                           ("HOLD", config.get("hold", "0"),
                            "Steady-state hold seconds after ramp (0 = run by loop count instead)"),
                           ("THINKTIME", config.get("thinktime", "500"),
                            "Base think time per step (ms); actual pacing varies up to ~2x"),
                           ("TIMEOUT", config.get("timeout", "30000"),
                            "Connect + response timeout (ms) — caps hung threads when the server stalls")]:
        a = _elem(coll, var, "Argument")
        _s(a, "Argument.name", var); _s(a, "Argument.value", val)
        _s(a, "Argument.metadata", "="); _s(a, "Argument.desc", desc)
    _s(tp, "TestPlan.user_define_classpath", "")
    return tp


def _add_thread_group(parent_ht, config: dict[str, str] | None = None):
    config = config or {}
    try:
        hold = int(str(config.get("hold", "0")).strip())
    except (TypeError, ValueError):
        hold = 0
    tg = SubElement(parent_ht, "ThreadGroup", {
        "guiclass": "ThreadGroupGui", "testclass": "ThreadGroup",
        "testname": "Users", "enabled": "true"})
    _s(tg, "ThreadGroup.on_sample_error", "continue")
    loop = _elem(tg, "ThreadGroup.main_controller", "LoopController")
    if hold > 0:
        # steady-state load: ramp up over RAMP, then hold — run is bounded by the scheduler duration
        # (RAMP + HOLD), so each thread loops forever until time runs out.
        _b(loop, "LoopController.continue_forever", False)
        _s(loop, "LoopController.loops", "-1")
        _s(tg, "ThreadGroup.num_threads", "${THREADS}")
        _s(tg, "ThreadGroup.ramp_time", "${RAMP}")
        _b(tg, "ThreadGroup.scheduler", True)
        _s(tg, "ThreadGroup.duration", "${__intSum(${RAMP},${HOLD})}")
        _s(tg, "ThreadGroup.delay", "0")
    else:
        _b(loop, "LoopController.continue_forever", False)
        _s(loop, "LoopController.loops", "${LOOPS}")
        _s(tg, "ThreadGroup.num_threads", "${THREADS}")
        _s(tg, "ThreadGroup.ramp_time", "${RAMP}")
        _b(tg, "ThreadGroup.scheduler", False)


def _primary_host(result: EngineResult) -> tuple[str, str]:
    """The most-common request host + its scheme — the target the plan repoints via ${BASE_URL}."""
    business = [r for r in result.capture.requests if not r.classification.excluded]
    hosts = Counter(r.request.host for r in business if r.request.host)
    if not hosts:
        return "", "https"
    host, _ = hosts.most_common(1)[0]
    proto = next((r.request.scheme for r in business if r.request.host == host), "https")
    return host, proto


def _add_http_defaults(parent_ht, result: EngineResult):
    host, _ = _primary_host(result)
    if not host:
        return
    cfg = SubElement(parent_ht, "ConfigTestElement", {
        "guiclass": "HttpDefaultsGui", "testclass": "ConfigTestElement",
        "testname": "HTTP Request Defaults", "enabled": "true"})
    _elem(cfg, "HTTPsampler.Arguments", "Arguments")
    _s(cfg, "HTTPSampler.domain", "${BASE_URL}")      # env-portable: edit BASE_URL to repoint
    _s(cfg, "HTTPSampler.protocol", "${PROTOCOL}")
    # Cap connect + response time. JMeter's default is no timeout, so a stalled server would block every
    # thread forever under load — the active-thread count balloons and throughput collapses with no
    # failure recorded. Inherited by every sampler; editable via the TIMEOUT variable.
    _s(cfg, "HTTPSampler.connect_timeout", "${TIMEOUT}")
    _s(cfg, "HTTPSampler.response_timeout", "${TIMEOUT}")
    SubElement(parent_ht, "hashTree")


def _add_cache_manager(parent_ht):
    """Cache + DNS managers at thread-group scope. Without a Cache Manager, cached static assets are
    re-fetched every iteration and load is overstated — clearEachIteration keeps each user realistic."""
    cm = SubElement(parent_ht, "CacheManager", {
        "guiclass": "CacheManagerGui", "testclass": "CacheManager",
        "testname": "HTTP Cache Manager", "enabled": "true"})
    _b(cm, "clearEachIteration", True)
    _b(cm, "useExpires", True)
    SubElement(parent_ht, "hashTree")
    dns = SubElement(parent_ht, "DNSCacheManager", {
        "guiclass": "DNSCachePanel", "testclass": "DNSCacheManager",
        "testname": "DNS Cache Manager", "enabled": "true"})
    _coll(dns, "DNSCacheManager.servers")
    _coll(dns, "DNSCacheManager.hosts")
    _b(dns, "DNSCacheManager.clearEachIteration", False)
    _b(dns, "DNSCacheManager.isCustomResolver", False)
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
            if low in skip or not hv or low in seen or not _replayable_header(hn):
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
    """Request scope: added inside the HTTP sampler's own subtree to require a 2xx/3xx code."""
    a = SubElement(parent_ht, "ResponseAssertion", {
        "guiclass": "AssertionGui", "testclass": "ResponseAssertion",
        "testname": "Assert Response Code (2xx/3xx)", "enabled": "true"})
    coll = _coll(a, "Asserion.test_strings")
    _s(coll, "assert_pattern", r"^(2\d\d|3\d\d)$")
    _s(a, "Assertion.test_field", "Assertion.response_code")
    _b(a, "Assertion.assume_success", False)
    _i(a, "Assertion.test_type", 1)   # 1 = Matches (regex)
    SubElement(parent_ht, "hashTree")


def _parse_iso(s: str):
    if not s:
        return None
    try:
        t = _re.sub(r"[+-]\d{2}:\d{2}$", "", _re.sub(r"Z$", "", str(s).strip()))
        return datetime.fromisoformat(t[:26])
    except (ValueError, TypeError):
        return None


def _observed_think_time(cap) -> int:
    """Median gap between consecutive business requests (ms), clamped to a sane 100–8000 — so default
    pacing reflects the real capture instead of a flat guess. Falls back to 500 when timings are absent."""
    stamps = []
    for r in cap.requests:
        if r.classification.excluded:
            continue
        t = _parse_iso(getattr(r.context, "started", "") or "")
        if t is not None:
            stamps.append(t)
    gaps = sorted((b - a).total_seconds() * 1000.0
                  for a, b in zip(stamps, stamps[1:]) if (b - a).total_seconds() >= 0)
    if not gaps:
        return 500
    median = gaps[len(gaps) // 2]
    return int(min(8000, max(100, median)))


def _add_think_time_pause(parent_ht):
    """A think-time pause BETWEEN user actions — emitted once before each Transaction Controller.

    A bare timer at thread-group scope applies to *every* sampler (JMeter scopes timers by subtree, not
    by tree position), so it would pause before every sub-request inside a transaction — inflating pacing
    and skewing throughput. Instead a Flow Control Action ("pause 0") carries the Uniform Random Timer as
    its OWN child, so the delay applies only to this standalone no-op step: the user pausing before the
    next action. The Test Action emits no sample, so it doesn't pollute the transaction timings or the
    response assertion. Each pause is uniformly ${THINKTIME}..2×${THINKTIME} ms."""
    ta = SubElement(parent_ht, "TestAction", {
        "guiclass": "TestActionGui", "testclass": "TestAction",
        "testname": "Think Time", "enabled": "true"})
    _i(ta, "ActionProcessor.action", 1)     # 1 = Pause
    _i(ta, "ActionProcessor.target", 0)     # 0 = current thread
    _s(ta, "ActionProcessor.duration", "0")  # the timer below supplies the delay
    ta_ht = SubElement(parent_ht, "hashTree")
    t = SubElement(ta_ht, "UniformRandomTimer", {
        "guiclass": "UniformRandomTimerGui", "testclass": "UniformRandomTimer",
        "testname": "Pause", "enabled": "true"})
    _s(t, "ConstantTimer.delay", "${THINKTIME}")
    _s(t, "RandomTimer.range", "${THINKTIME}")
    SubElement(ta_ht, "hashTree")


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
    # We write an explicit header row AND set variableNames, so JMeter must skip that first line —
    # otherwise (its default of false) it reads the header as data and the first virtual user submits
    # the column names as values ("firstname", "email", …). ignoreFirstLine only applies when
    # variableNames is non-empty, which it always is here.
    _b(cfg, "ignoreFirstLine", True)
    _s(cfg, "delimiter", ",")
    _b(cfg, "quotedData", True)
    _b(cfg, "recycle", True)
    _b(cfg, "stopThread", False)
    _s(cfg, "shareMode", "shareMode.all")
    SubElement(parent_ht, "hashTree")


# ---------------------------------------------------------------- top level

def _build_jmx_tree(result: EngineResult, config: dict[str, str] | None = None,
                    csv_files: dict[str, str] | None = None) -> bytes:
    config = dict(config or {})
    csv_files = csv_files or {}
    base_url, protocol = _primary_host(result)
    # when the caller doesn't set a think time, default to the capture's own observed pacing
    if not str(config.get("thinktime", "")).strip():
        config["thinktime"] = str(_observed_think_time(result.capture))
    sub = _build_sub_map(result)
    bindings = VariableBindings(result)
    redirects = redirect_execution(result, _replayable_header)
    # extractor self-check: only ship an extractor proven to resolve; refine ambiguous JSONPaths; drop
    # (and let the manual-review path flag) any that could not be verified against the capture.
    check_by_var = {chk.variable: chk for chk in result.extractor_checks}
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
    _add_test_plan(root_ht, name, config, comment, base_url=base_url, protocol=protocol)
    plan_ht = SubElement(root_ht, "hashTree")

    _add_thread_group(plan_ht, config)
    tg_ht = SubElement(plan_ht, "hashTree")

    cap = result.capture
    business = [r for r in cap.requests if not r.classification.excluded]
    common_headers = _collect_common_headers(business)
    global_header_names = frozenset(common_headers)
    cookie_mgr_values = _cookie_manager_values(result)

    _add_http_defaults(tg_ht, result)
    _add_cookie_manager(tg_ht)
    _add_cache_manager(tg_ht)                                 # realistic caching — no re-fetch per iteration
    _add_global_header_manager(tg_ht, common_headers, sub)   # every plan gets an HTTP Header Manager
    for d in result.parameterization.datasets:
        fname = csv_files.get(d.name, f"{d.name.lower()}.csv")
        _add_csv_dataset(tg_ht, d.name, fname, [bindings.parameter_name(d, c) for c in d.columns])

    emitted_txns = 0
    for txn in result.transactions:
        biz = [i for i in txn.request_indices if not cap.requests[i].classification.excluded]
        if not biz:
            continue
        # Think time models the user's pause BETWEEN business transactions: emitted between consecutive
        # Transaction Controllers only — never before the first one, and never between the sub-requests
        # inside a transaction. The pause is scoped to a no-op Test Action so it can't pace the samplers.
        if emitted_txns:
            _add_think_time_pause(tg_ht)
        tc = SubElement(tg_ht, "TransactionController", {
            "guiclass": "TransactionControllerGui", "testclass": "TransactionController",
            "testname": txn.name, "enabled": "true"})
        _b(tc, "TransactionController.parent", True)
        _b(tc, "TransactionController.includeTimers", False)
        tc_ht = SubElement(tg_ht, "hashTree")
        for idx in biz:
            if idx in redirects.automatic_targets:
                continue  # Executed exactly once by its preceding redirect follower.
            req = cap.requests[idx]
            produced = producer_map.get(idx, [])
            # if this request produces a value read from its redirect, it must not follow the redirect
            follow = idx not in redirects.explicit_sources and not any(c.from_redirect for c in produced)
            redirect_source = redirects.location_targets.get(idx)
            redirect_target = (f"${{{location_variable(redirect_source)}}}" if redirect_source is not None else "")
            _add_http_sampler(tc_ht, req, sub, follow_redirects=follow, global_headers=global_header_names,
                              cookie_mgr_values=cookie_mgr_values, primary_host=base_url,
                              slot_subs=_param_slot_subs(result, idx, bindings), redirect_target=redirect_target,
                              encoded_form_bindings=_encoded_form_bindings(result, idx, sub))
            # the sampler's own hashTree is the last child of tc_ht
            sampler_ht = list(tc_ht)[-1]
            if idx in redirects.location_targets.values():
                add_location_capture(sampler_ht, idx, SubElement, _s, _add_regex_extractor)
            auth_produced = [c for c in produced if authentication_dependency(result, c)]
            add_runtime_checks(sampler_ht, auth_produced, SubElement, _s)
            for c in produced:
                chk = check_by_var.get(c.variable)
                if chk is not None and not chk.ok:
                    # Omit unverifiable extractors. Accepted auth still consumes a
                    # runtime variable and stops at the producer; other values keep
                    # the existing literal/manual-review policy.
                    continue
                if c.extractor == ExtractorType.JSON:
                    expr = chk.refined_expression if (chk and chk.refined_expression) else c.expression
                    _add_json_extractor(sampler_ht, c.variable, expr)
                else:
                    use_headers = c.producer_location.startswith(("set-cookie:", "response.header:", "response.location:", "response.locpath:"))
                    expr = (cookie_value_expression(c.producer_location.split(':', 1)[1])
                            if c.producer_location.startswith('set-cookie:') else c.expression)
                    _add_regex_extractor(sampler_ht, c.variable, expr, use_headers)
                    if c in auth_produced and cookie_decoding_required(result, c):
                        add_cookie_normalization(sampler_ht, c.variable, SubElement, _s)
                # Only guard correlations with residual doubt. A correlation proven correct against the
                # capture (extractor verified UNIQUE) with strong lifecycle evidence (High confidence) is
                # 100% right — no runtime "did it resolve?" review needed, it would just add clutter. Keep
                # the false-green guard where doubt remains: an ambiguous path we had to refine, or
                # Medium/Low confidence — exactly where a NOT_FOUND is actually plausible.
                certain = chk is not None and chk.status == ExtractorStatus.UNIQUE and c.confidence == "High"
                if not certain:
                    _add_correlation_health_assertion(sampler_ht, c.variable)
            _add_response_assertion(sampler_ht)
        emitted_txns += 1

    rough = tostring(root, encoding="utf-8")
    return minidom.parseString(rough).toprettyxml(indent="  ", encoding="utf-8")


_JMX_VAR_RE = _re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _prune_unused_parameters(result: EngineResult, xml: bytes) -> bool:
    """Usage-aware CSV: drop every dataset column the generated plan never references.

    A parameter candidate earns a CSV column only when a ``${column}`` actually appears in a generated
    sampler. A column can survive discovery yet reference nothing — e.g. its values are too short to
    substitute safely (a numeric ``id`` of "1"/"11", which `_sub_ok` refuses because it would collide),
    the value only occurred in an excluded request, or the same value was claimed by a correlation
    variable instead. Such a column is dead weight: it bloats the CSV and misleads the engineer. Here we
    intersect the datasets with the variables the JMX truly uses, remove the unreferenced columns, drop
    any dataset left empty, and collapse rows that become duplicates once a distinguishing column is
    gone. Returns True when anything changed (so the caller rebuilds the plan without the dead columns).
    """
    referenced = set(_JMX_VAR_RE.findall(xml.decode("utf-8") if isinstance(xml, (bytes, bytearray)) else xml))
    bindings = VariableBindings(result)
    changed = False
    kept: list = []
    for d in result.parameterization.datasets:
        cols = [c for c in d.columns if bindings.parameter_name(d, c) in referenced]
        if len(cols) != len(d.columns):
            changed = True
        if not cols:
            continue                                   # no referenced column → the whole dataset is unused
        if len(cols) != len(d.columns):
            names = [c.name for c in cols]
            rows, seen = [], set()
            for r in d.rows:
                row = {n: r.get(n, "") for n in names}
                key = tuple(row[n] for n in names)
                if key in seen:                        # a distinguishing column was removed → dedupe
                    continue
                seen.add(key)
                rows.append(row)
            d.columns = cols
            d.rows = rows
        kept.append(d)
    if changed:
        result.parameterization.datasets = kept
    return changed


def build_jmx_xml(result: EngineResult, config: dict[str, str] | None = None,
                  csv_files: dict[str, str] | None = None) -> bytes:
    """Build the JMeter plan, then prune any parameter the plan does not actually reference so the CSV
    is the minimum data the script needs (usage-aware). Pruning mutates ``result.parameterization`` so
    the CSV files written by :func:`emit_jmx` stay in lock-step with the plan's ``${variables}``."""
    xml = _build_jmx_tree(result, config, csv_files)
    if _prune_unused_parameters(result, xml):
        xml = _build_jmx_tree(result, config, csv_files)      # rebuild without the dead CSV columns
    return xml


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


def _manual_review_markdown(result: EngineResult, jmx_name: str, jmx_xml: bytes | None = None) -> str | None:
    """Readable checklist of values the engine could not auto-correlate; None when there are none."""
    from har2jmx.webreport import build_manual_correlations
    items = build_manual_correlations(result, jmx_xml)
    if not items:
        return None
    lines = [
        "# Manual Correlation Needed",
        "",
        f"**Plan:** {jmx_name}.jmx",
        f"**{len(items)} value(s)** are sent in requests but could not be automatically correlated.",
        "The plan has missing or incomplete runtime bindings for these values. Review the producer",
        "and each downstream request before running at scale.",
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
    # Build the plan FIRST: build_jmx_xml prunes any parameter the plan never references, so the CSV
    # files written below reflect only the columns the JMX actually uses (usage-aware, no dead columns).
    csv_files: dict[str, str] = {d.name: f"{name}_{d.name.lower()}.csv"
                                 for d in result.parameterization.datasets}
    xml = build_jmx_xml(result, config, csv_files)
    jmx_path = out / f"{name}.jmx"
    jmx_path.write_bytes(xml)

    bindings = VariableBindings(result)
    csv_paths: list[Path] = []
    for d in result.parameterization.datasets:           # datasets are now the pruned set
        fname = csv_files[d.name]
        path = out / fname
        cols = [c.name for c in d.columns]
        observed: list[tuple] = []
        seen: set[tuple] = set()
        for row in bindings.parameter_rows(d):          # owned initial row + observed variation
            cells = tuple(str(row.get(c, "")) for c in cols)
            if cells not in seen:
                seen.add(cells)
                observed.append(cells)
        rows = _synthesize_rows(cols, observed, target)  # grow safe data toward N users
        with path.open("w", newline="", encoding="utf-8") as fh:
            w = _csv.writer(fh)
            w.writerow([bindings.parameter_name(d, c) for c in d.columns])
            w.writerows(rows)
        csv_paths.append(path)

    report_paths: list[Path] = []
    review_md = _manual_review_markdown(result, name, xml)
    if review_md:
        review_path = out / f"{name}_manual_review.md"
        review_path.write_text(review_md, encoding="utf-8")
        report_paths.append(review_path)

    return jmx_path, csv_paths, report_paths
