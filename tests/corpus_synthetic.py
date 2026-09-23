"""SYNTHETIC 100-scenario validation corpus for the HAR->JMX engine.

These are hand-built synthetic HAR patterns (NOT real captured applications) that assert the
performance-engineering behaviour the engine must exhibit: noise exclusion, dependency retention,
correlation vs parameterization by origin, static hardcoding, minimal usage-derived CSV, one response
assertion per transaction, and between-transaction think time.

Each scenario is analyzed by the real engine (`har2jmx.engine.analyze` + `emit.build_jmx_xml`) and its
checks are evaluated against the actual generated JMX/CSV. Run as a module to print the defect matrix;
imported by test_synthetic_corpus.py for the pytest gate.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Callable
from xml.dom import minidom

from har2jmx.emit import build_jmx_xml
from har2jmx.engine import analyze

_UDV = {"THREADS", "LOOPS", "RAMP", "THINKTIME", "BASE_URL", "PROTOCOL", "HOLD", "DURATION", "TIMEOUT"}
_T0 = "2024-01-01T10:00:"


def entry(method, url, *, hdr=None, body=None, raw=None, ctype="application/json", resp="{}",
          rmime="application/json", set_cookie=None, status=None, sec=0, page="p1", restype=""):
    H = [{"name": "Content-Type", "value": ctype}, {"name": "Accept", "value": "application/json"},
         {"name": "User-Agent", "value": "Mozilla/5.0"}]
    for k, v in (hdr or {}).items():
        H.append({"name": k, "value": v})
    rh = [{"name": "Content-Type", "value": rmime}]
    if set_cookie:
        rh.append({"name": "Set-Cookie", "value": set_cookie})
    if status is None:
        status = 201 if (method == "POST" and re.search(r"/(orders?|claims?|policies|customers?)$", url)) else 200
    ent = {"pageref": page, "_resourceType": restype, "startedDateTime": f"{_T0}{sec:02d}.000Z", "time": 60,
           "request": {"method": method, "url": url, "httpVersion": "HTTP/1.1",
                       "headers": H, "queryString": [], "cookies": []},
           "response": {"status": status, "headers": rh, "cookies": [],
                        "content": {"mimeType": rmime, "text": resp}}}
    if raw is not None:
        ent["request"]["postData"] = {"mimeType": ctype, "text": raw}
    elif body is not None:
        ent["request"]["postData"] = {"mimeType": ctype, "text": json.dumps(body)}
    return ent


# ---- context computed once per scenario from the ACTUAL generated artifacts ---------------------

@dataclass
class Ctx:
    res: object
    xml: str
    csv_cols: list
    jvars: set
    kept_hosts: set
    excluded_hosts: set
    kept_paths: list
    extractor_vars: set
    tg_level_assertions: int
    txn_assertion_counts: list
    thinktime_count: int
    txn_count: int


def _elems(n):
    return [c for c in n.childNodes if c.nodeType == c.ELEMENT_NODE]


def _direct_response_code_assertions(container):
    kids = _elems(container)
    out, i = [], 0
    while i < len(kids):
        e = kids[i]
        ht = kids[i + 1] if i + 1 < len(kids) and kids[i + 1].tagName == "hashTree" else None
        if e.tagName == "ResponseAssertion" and "Assertion.response_code" in e.toxml():
            out.append(e)
        i += 2 if ht is not None else 1
    return out


def _deep_response_code_assertions(container):
    # the response assertion now nests under the transaction's anchor sampler, so count the whole subtree
    return [n for n in container.getElementsByTagName("ResponseAssertion")
            if "Assertion.response_code" in n.toxml()]


def _walk_structure(doc):
    """Return (tg_level_assertion_count, [per-transaction assertion counts], thinktime_count, txn_count)."""
    tg = None

    def find_tg(container):
        nonlocal tg
        kids = _elems(container)
        i = 0
        while i < len(kids):
            e = kids[i]
            ht = kids[i + 1] if i + 1 < len(kids) and kids[i + 1].tagName == "hashTree" else None
            if e.tagName == "ThreadGroup" and ht is not None:
                tg = ht
                return
            if e.tagName == "hashTree":
                find_tg(e)
            elif ht is not None:
                find_tg(ht)
            i += 2 if ht is not None else 1
    find_tg(doc.documentElement)
    if tg is None:
        return 0, [], 0, 0
    tg_level = len(_direct_response_code_assertions(tg))
    txn_counts, thinktime, txns = [], 0, 0
    kids = _elems(tg)
    i = 0
    while i < len(kids):
        e = kids[i]
        ht = kids[i + 1] if i + 1 < len(kids) and kids[i + 1].tagName == "hashTree" else None
        if e.tagName == "TransactionController" and ht is not None:
            txns += 1
            txn_counts.append(len(_deep_response_code_assertions(ht)))
        elif e.tagName == "TestAction" and "Think Time" in e.getAttribute("testname"):
            thinktime += 1
        i += 2 if ht is not None else 1
    return tg_level, txn_counts, thinktime, txns


def build_ctx(entries, config=None):
    res = analyze(json.dumps({"log": {"version": "1.2", "entries": entries}}).encode())
    xml = build_jmx_xml(res, config or {"threads": "5"}).decode()
    cols = []
    for names in re.findall(r'variableNames">([^<]+)<', xml):
        cols += [c.strip() for c in names.split(",") if c.strip()]
    jvars = set(re.findall(r"\$\{(\w+)\}", xml)) - _UDV
    extractor_vars = set(re.findall(r'referenceNames">([^<]+)<', xml)) | \
        set(re.findall(r'RegexExtractor\.refname">([^<]+)<', xml))
    kept = {r.request.host for r in res.capture.requests if not r.classification.excluded}
    excl = {r.request.host for r in res.capture.requests if r.classification.excluded}
    kept_paths = [r.request.path for r in res.capture.requests if not r.classification.excluded]
    tg_lvl, txn_counts, tt, txns = _walk_structure(minidom.parseString(xml))
    return Ctx(res, xml, cols, jvars, kept, excl, kept_paths, extractor_vars,
               tg_lvl, txn_counts, tt, txns)


# ---- check DSL ----------------------------------------------------------------------------------

def host_excluded(h):   return (f"host {h} excluded", lambda c: (h in c.excluded_hosts and h not in c.kept_hosts, f"excluded={h in c.excluded_hosts}"))
def host_kept(h):       return (f"host {h} kept", lambda c: (h in c.kept_hosts, f"kept={h in c.kept_hosts}"))
def not_in_jmx(s):      return (f"'{s}' absent from JMX", lambda c: (s not in c.xml, f"present={s in c.xml}"))
def in_jmx(s):          return (f"'{s}' present in JMX", lambda c: (s in c.xml, f"present={s in c.xml}"))
def param(v):           return (f"{v} parameterized (CSV col + ${{var}})", lambda c: (v in c.csv_cols and v in c.jvars, f"csv={v in c.csv_cols},var={v in c.jvars}"))
def not_param(v):       return (f"{v} NOT a CSV column", lambda c: (v not in c.csv_cols, f"in_csv={v in c.csv_cols}"))
def correlated(var):    return (f"{var} correlated (extractor, not CSV)", lambda c: (var in c.extractor_vars and var not in c.csv_cols, f"extractor={var in c.extractor_vars},in_csv={var in c.csv_cols}"))
def var_used(var):      return (f"${{{var}}} used in JMX", lambda c: (var in c.jvars, f"used={var in c.jvars}"))
def no_unused_csv():    return ("no unused CSV columns", lambda c: (set(c.csv_cols) <= c.jvars, f"unused={sorted(set(c.csv_cols)-c.jvars)}"))
def no_dup_csv():       return ("no duplicate CSV variable names", lambda c: (len(c.csv_cols) == len(set(c.csv_cols)), f"dups={[x for x in set(c.csv_cols) if c.csv_cols.count(x)>1]}"))
def no_tg_assertion():  return ("no response assertion at Thread Group level", lambda c: (c.tg_level_assertions == 0, f"tg_level={c.tg_level_assertions}"))
def one_assertion_per_txn(): return ("exactly one response assertion per transaction", lambda c: (all(n == 1 for n in c.txn_assertion_counts) and len(c.txn_assertion_counts) > 0, f"per_txn={c.txn_assertion_counts}"))
def thinktime_between():     return ("think time strictly between transactions (N-1)", lambda c: (c.thinktime_count == max(c.txn_count - 1, 0), f"tt={c.thinktime_count},txn={c.txn_count}"))
def csv_cols_exactly(names): return (f"CSV columns == {sorted(names)}", lambda c: (set(c.csv_cols) == set(names), f"actual={sorted(c.csv_cols)}"))
def csv_max(n):         return (f"CSV has <= {n} columns", lambda c: (len(c.csv_cols) <= n, f"count={len(c.csv_cols)}"))


@dataclass
class Scenario:
    sid: str
    archetype: str
    entries: list
    checks: list
    config: dict = field(default_factory=lambda: {"threads": "5"})


# convenience builders reused across scenarios
def login(host="app.example.com", form=True, sec=0, page="p1"):
    if form:
        return entry("POST", f"https://{host}/api/login", ctype="application/x-www-form-urlencoded",
                     raw="signInName=perfSuperuser%40mailinator.com&password=Aug%402026",
                     set_cookie="JSESSIONID=sess-abc-123; Path=/",
                     resp='{"access_token":"TKN-987"}', sec=sec, page=page)
    return entry("POST", f"https://{host}/api/login",
                 body={"signInName": "perfSuperuser@mailinator.com", "password": "Aug@2026"},
                 set_cookie="JSESSIONID=sess-abc-123; Path=/",
                 resp='{"access_token":"TKN-987"}', sec=sec, page=page)


def bearer():
    return {"Authorization": "Bearer TKN-987"}


def SCENARIOS():
    S = []

    # ---- Noise families: each noise host must be excluded, business kept ----
    noise_hosts = [
        ("maps.googleapis.com", "/maps/api/js?key=K", "text/javascript"),
        ("maps.googleapis.com", "/maps/api/geocode/json?a=NYC", "application/json"),
        ("maps.gstatic.com", "/maps/tile.png", "image/png"),
        ("www.google-analytics.com", "/g/collect?v=2", "image/gif"),
        ("www.googletagmanager.com", "/gtm.js", "application/javascript"),
        ("browser-intake-datadoghq.com", "/api/v2/rum", "application/json"),
        ("nr-data.net", "/1/abc", "application/json"),
        ("fonts.gstatic.com", "/s/font.woff2", "font/woff2"),
        ("fonts.googleapis.com", "/css2?family=Roboto", "text/css"),
        ("cdnjs.cloudflare.com", "/ajax/libs/jquery/3.6.0/jquery.min.js", "application/javascript"),
        ("cdn.jsdelivr.net", "/npm/chart.js", "application/javascript"),
        ("www.google.com", "/recaptcha/api2/anchor", "text/html"),
        ("connect.facebook.net", "/en_US/sdk.js", "application/javascript"),
        ("static.hotjar.com", "/c/hotjar.js", "application/javascript"),
        ("widget.intercom.io", "/widget/abc", "application/javascript"),
    ]
    for i, (h, p, mime) in enumerate(noise_hosts, 1):
        S.append(Scenario(
            f"noise-{i:02d}", "third-party/telemetry/static noise",
            [login(sec=0),
             entry("GET", f"https://{h}{p}", rmime=mime, sec=2, page="p2"),
             entry("GET", "https://app.example.com/api/orders", hdr=bearer(), resp='{"orderId":"ORD-1"}', sec=3, page="p2")],
            [host_excluded(h), host_kept("app.example.com"), not_in_jmx(h)]))

    # static asset by path/extension
    for i, (path, mime) in enumerate([("/assets/app.css", "text/css"), ("/static/app.js", "application/javascript"),
                                      ("/img/logo.png", "image/png"), ("/fonts/x.woff2", "font/woff2")], 1):
        S.append(Scenario(
            f"static-{i:02d}", "static browser asset",
            [login(sec=0), entry("GET", f"https://app.example.com{path}", rmime=mime, sec=2, page="p2"),
             entry("GET", "https://app.example.com/api/products", hdr=bearer(), resp='{"items":[]}', sec=3, page="p2")],
            [not_in_jmx(path), host_kept("app.example.com")]))

    # CORS preflight OPTIONS excluded
    S.append(Scenario("preflight-01", "CORS preflight",
        [entry("OPTIONS", "https://app.example.com/api/orders", sec=0),
         login(sec=1), entry("POST", "https://app.example.com/api/orders", hdr=bearer(), body={"item": "x"}, resp='{"orderId":"O-1"}', sec=2)],
        [not_in_jmx("OPTIONS"), host_kept("app.example.com")]))

    # ---- Dependency retention: required external hosts kept ----
    for i, h in enumerate(["auth.identity-provider.com", "login.microsoftonline.com", "api.partner-backend.com",
                           "payments.stripe-like.com", "sso.okta-like.com"], 1):
        S.append(Scenario(
            f"dependency-{i:02d}", "required external dependency",
            [entry("POST", f"https://{h}/oauth/token", ctype="application/x-www-form-urlencoded",
                   raw="signInName=perfSuperuser%40mailinator.com&password=Aug%402026", resp='{"access_token":"TKN-1"}', sec=0),
             entry("GET", "https://app.example.com/api/customers", hdr=bearer(), resp='{"customers":[]}', sec=2)],
            [host_kept(h)]))

    # ---- Auth families: creds parameterized, token/session correlated ----
    S.append(Scenario("auth-form", "form login",
        [login(form=True, sec=0), entry("GET", "https://app.example.com/api/me", hdr=bearer(), resp='{"id":"U1"}', sec=2)],
        [param("signInName"), param("password"), not_in_jmx("Aug@2026")]))
    S.append(Scenario("auth-json", "json login",
        [login(form=False, sec=0), entry("GET", "https://app.example.com/api/me", hdr=bearer(), resp='{"id":"U1"}', sec=2)],
        [param("signInName"), param("password")]))
    S.append(Scenario("auth-csrf", "csrf token flow",
        [entry("GET", "https://app.example.com/api/csrf", resp='{"csrfToken":"CS-abc123xyz"}', sec=0),
         entry("POST", "https://app.example.com/api/orders", hdr={"X-CSRF-Token": "CS-abc123xyz"}, body={"item": "x"}, resp='{"orderId":"O-1"}', sec=2)],
        [correlated("csrfToken"), not_param("csrfToken")]))

    # ---- ID origin families: server-generated -> correlate; user/existing -> parameterize ----
    # server id in path
    S.append(Scenario("id-path-server", "server id in URL path",
        [login(sec=0),
         entry("POST", "https://app.example.com/api/orders", hdr=bearer(), body={"item": "x"}, resp='{"orderId":"ORD-77"}', sec=2),
         entry("GET", "https://app.example.com/api/orders/ORD-77", hdr=bearer(), resp='{"orderId":"ORD-77"}', sec=4, page="p2")],
        [correlated("orderId"), not_param("orderId"), in_jmx("/api/orders/${orderId}")]))
    # server id in query
    S.append(Scenario("id-query-server", "server id in query",
        [login(sec=0),
         entry("POST", "https://app.example.com/api/orders", hdr=bearer(), body={"item": "x"}, resp='{"orderId":"ORD-88"}', sec=2),
         entry("GET", "https://app.example.com/api/track?orderId=ORD-88", hdr=bearer(), resp='{"ok":true}', sec=4, page="p2")],
        [correlated("orderId"), not_param("orderId")]))
    # server id in header
    S.append(Scenario("id-header-server", "server id in header",
        [login(sec=0),
         entry("POST", "https://app.example.com/api/session", hdr=bearer(), body={"x": 1}, resp='{"workflowId":"WF-abcdef12"}', sec=2),
         entry("GET", "https://app.example.com/api/step", hdr={"X-Workflow-Id": "WF-abcdef12", **bearer()}, resp='{"ok":true}', sec=4, page="p2")],
        [correlated("workflowId"), not_param("workflowId")]))
    # server id in nested JSON
    S.append(Scenario("id-nested-server", "server id nested JSON",
        [login(sec=0),
         entry("POST", "https://app.example.com/api/claims", hdr=bearer(), body={"x": 1}, resp='{"data":{"claim":{"patientAdviceId":"PA-90210"}}}', sec=2),
         entry("GET", "https://app.example.com/api/advice?patientAdviceId=PA-90210", hdr=bearer(), resp='{"ok":true}', sec=4, page="p2")],
        [correlated("patientAdviceId"), not_param("patientAdviceId")]))

    # ---- Static config families: hardcoded, never CSV ----
    static_qs = [("apiVersion", "v2"), ("sortOrder", "asc"), ("locale", "en-US"), ("view", "grid"),
                 ("format", "json"), ("theme", "dark")]
    for i, (k, v) in enumerate(static_qs, 1):
        S.append(Scenario(
            f"static-cfg-{i:02d}", "static configuration value",
            [login(sec=0), entry("GET", f"https://app.example.com/api/products?{k}={v}&q=laptop", hdr=bearer(), resp='{"items":[]}', sec=2)],
            [not_param(k)]))

    # ---- Business input families: parameterized ----
    biz_bodies = [
        ("customerNumber", {"customerNumber": "CUST-55501"}),
        ("accountNumber", {"accountNumber": "ACCT-778812"}),
        ("policyNumber", {"policyNumber": "POL-2024-9981"}),
        ("claimNumber", {"claimNumber": "CLM-556677"}),
        ("searchTerm", {"searchTerm": "wireless headphones"}),
    ]
    for i, (name, body) in enumerate(biz_bodies, 1):
        S.append(Scenario(
            f"biz-input-{i:02d}", "business input parameterized",
            [login(sec=0), entry("POST", "https://app.example.com/api/lookup", hdr=bearer(), body=body, resp='{"ok":true}', sec=2)],
            [param(name)]))

    # ---- Correlation-vs-parameterization conflict ----
    # customerId server-generated (from login) must NOT be parameterized despite the name
    S.append(Scenario("conflict-customerId", "server customerId not parameterized",
        [entry("POST", "https://app.example.com/api/login", ctype="application/x-www-form-urlencoded",
               raw="signInName=perfSuperuser%40mailinator.com&password=Aug%402026",
               resp='{"access_token":"TKN-1","customerId":"CUST-900"}', set_cookie="JSESSIONID=s-1; Path=/", sec=0),
         entry("GET", "https://app.example.com/api/customers/CUST-900", hdr=bearer(), resp='{"customerId":"CUST-900"}', sec=2, page="p2")],
        [correlated("customerId"), not_param("customerId")]))
    # duplicate logical value -> one column
    S.append(Scenario("conflict-duplicate", "duplicate business value one column",
        [login(form=True, sec=0),
         entry("POST", "https://app.example.com/api/profile", hdr=bearer(),
               body={"signInName": "perfSuperuser@mailinator.com", "note": "hello there note"}, resp='{"ok":true}', sec=2, page="p2")],
        [(("signInName appears once in CSV"), lambda c: (c.csv_cols.count("signInName") == 1, f"count={c.csv_cols.count('signInName')}"))]))
    # unused discovered value -> no column (short id 1/2 can't substitute)
    S.append(Scenario("edge-unused", "unused candidate no CSV column",
        [login(sec=0), entry("GET", "https://app.example.com/api/items?page=2&status=OK", hdr=bearer(), resp='{"rows":[{"ref":"R-1"}]}', sec=2)],
        [no_unused_csv()]))

    # ---- Structure: assertion + think time across multiple transactions ----
    multi = [login(sec=0),
             entry("GET", "https://app.example.com/api/customers?q=acme", hdr=bearer(), resp='{"customers":[]}', sec=6, page="p2"),
             entry("POST", "https://app.example.com/api/orders", hdr=bearer(), body={"item": "x"}, resp='{"orderId":"O-1"}', sec=12, page="p3")]
    S.append(Scenario("struct-assert", "one assertion per transaction", multi,
        [no_tg_assertion(), one_assertion_per_txn()]))
    S.append(Scenario("struct-thinktime", "think time between transactions", multi,
        [thinktime_between()]))
    S.append(Scenario("struct-single", "single transaction has no think time",
        [entry("POST", "https://app.example.com/api/orders", body={"item": "x"}, resp='{"orderId":"O-1"}', sec=0)],
        [(("no think time for single txn"), lambda c: (c.thinktime_count == 0, f"tt={c.thinktime_count}"))]))

    # ---- App archetype end-to-end (each: noise out, business in, CSV minimal) ----
    archetypes = [
        ("spa-react", [login(sec=0),
                       entry("GET", "https://maps.googleapis.com/maps/api/js", rmime="text/javascript", sec=1, page="p2"),
                       entry("GET", "https://www.google-analytics.com/g/collect", rmime="image/gif", sec=1, page="p2"),
                       entry("GET", "https://app.example.com/static/main.js", rmime="application/javascript", sec=1, page="p2"),
                       entry("GET", "https://app.example.com/api/feed", hdr=bearer(), resp='{"items":[]}', sec=2, page="p2")]),
        ("graphql", [login(sec=0),
                     entry("POST", "https://app.example.com/graphql", hdr=bearer(),
                           body={"operationName": "GetOrders", "query": "query GetOrders{orders{id}}"}, resp='{"data":{"orders":[]}}', sec=2, page="p2")]),
        ("microservices", [login(sec=0),
                           entry("GET", "https://svc-a.example.com/api/a", hdr=bearer(), resp='{"a":1}', sec=2, page="p2"),
                           entry("GET", "https://svc-b.example.com/api/b", hdr=bearer(), resp='{"b":2}', sec=3, page="p2"),
                           entry("GET", "https://www.google-analytics.com/g/collect", rmime="image/gif", sec=3, page="p2")]),
    ]
    for name, ents in archetypes:
        S.append(Scenario(f"arch-{name}", f"end-to-end {name}", ents,
            [not_in_jmx("google-analytics"), not_in_jmx("maps.googleapis.com"), no_unused_csv(), no_dup_csv()]))

    # ---- Fill to ~100 with parameter/location variations that must stay hardcoded or param correctly ----
    # numeric-but-static values must not be parameterized just for being numeric
    for i, (k, v) in enumerate([("limit", "50"), ("offset", "0"), ("pageSize", "25"), ("timeout", "30"),
                                ("version", "3"), ("count", "10")], 1):
        S.append(Scenario(
            f"numeric-static-{i:02d}", "numeric static not parameterized",
            [login(sec=0), entry("GET", f"https://app.example.com/api/list?{k}={v}&q=phones", hdr=bearer(), resp='{"rows":[]}', sec=2)],
            [not_param(k)]))

    # bearer/session/csrf tokens never in CSV
    S.append(Scenario("tokens-not-csv", "runtime tokens never CSV",
        [entry("POST", "https://app.example.com/api/login", ctype="application/x-www-form-urlencoded",
               raw="signInName=perfSuperuser%40mailinator.com&password=Aug%402026",
               resp='{"access_token":"TKN-xyz987","refresh_token":"RFR-abc123def"}', set_cookie="JSESSIONID=sess-1; Path=/", sec=0),
         entry("GET", "https://app.example.com/api/me", hdr=bearer(), resp='{"id":"U1"}', sec=2, page="p2")],
        [not_param("access_token"), not_param("refresh_token"), not_param("JSESSIONID")]))

    # ---- more app archetypes: each keeps its business API + excludes injected noise ----
    arch2 = [
        ("angular", "app.example.com", "/api/dashboard"),
        ("vue", "app.example.com", "/api/feed"),
        ("aspnet-mvc", "portal.example.com", "/Home/Data"),
        ("spring-boot", "api.example.com", "/api/v1/orders"),
        ("nodejs-bff", "bff.example.com", "/bff/summary"),
        ("java-ee", "app.example.com", "/rest/accounts"),
        ("salesforce", "myorg.my.salesforce.com", "/services/data/v58.0/query"),
        ("servicenow", "myorg.service-now.com", "/api/now/table/incident"),
        ("sap", "sap.example.com", "/sap/opu/odata/sap/SERVICE"),
        ("guidewire", "pc.example.com", "/pc/service/policy"),
        ("sharepoint", "myorg.sharepoint.com", "/_api/web/lists"),
    ]
    for name, host, path in arch2:
        S.append(Scenario(f"arch2-{name}", f"end-to-end {name}",
            [login(host=host, sec=0),
             entry("GET", "https://www.google-analytics.com/g/collect", rmime="image/gif", sec=1, page="p2"),
             entry("GET", "https://maps.googleapis.com/maps/api/js", rmime="text/javascript", sec=1, page="p2"),
             entry("GET", f"https://{host}{path}", hdr=bearer(), resp='{"data":[]}', sec=2, page="p2")],
            [host_kept(host), not_in_jmx("google-analytics"), not_in_jmx("maps.googleapis.com")]))

    # ---- SAML: SAMLResponse is server-issued -> correlated, auth host kept ----
    S.append(Scenario("saml-flow", "SAML SSO",
        [entry("GET", "https://idp.example.com/saml/sso", rmime="text/html",
               resp='{"SAMLResponse":"PHNhbWxassertionABCDEF1234567890"}', sec=0),
         entry("POST", "https://app.example.com/saml/acs", hdr={},
               raw="SAMLResponse=PHNhbWxassertionABCDEF1234567890", ctype="application/x-www-form-urlencoded",
               resp='{"ok":true}', sec=2, page="p2")],
        [host_kept("idp.example.com"), host_kept("app.example.com")]))

    # ---- multipart upload: upload endpoint kept ----
    up = {"pageref": "p2", "startedDateTime": _T0 + "02.000Z", "time": 60,
          "request": {"method": "POST", "url": "https://app.example.com/api/documents/upload",
                      "headers": [{"name": "Content-Type", "value": "multipart/form-data; boundary=X"},
                                  {"name": "Authorization", "value": "Bearer TKN-987"}],
                      "queryString": [], "cookies": [],
                      "postData": {"mimeType": "multipart/form-data; boundary=X",
                                   "params": [{"name": "file", "fileName": "doc.pdf", "contentType": "application/pdf"}],
                                   "text": "--X"}},
          "response": {"status": 200, "headers": [{"name": "Content-Type", "value": "application/json"}],
                       "cookies": [], "content": {"mimeType": "application/json", "text": '{"docId":"D-1"}'}}}
    S.append(Scenario("multipart-upload", "multipart file upload",
        [login(sec=0), up], [host_kept("app.example.com"), in_jmx("/api/documents/upload")]))

    # ---- redirect: id issued in Location header, reused -> correlated ----
    redir = {"pageref": "p1", "startedDateTime": _T0 + "02.000Z", "time": 60,
             "request": {"method": "POST", "url": "https://app.example.com/api/orders",
                         "headers": [{"name": "Authorization", "value": "Bearer TKN-987"},
                                     {"name": "Content-Type", "value": "application/json"}],
                         "queryString": [], "cookies": [], "postData": {"mimeType": "application/json", "text": '{"item":"x"}'}},
             "response": {"status": 302, "headers": [{"name": "Location", "value": "/api/orders/ORD-REDIR-991"}],
                          "cookies": [], "content": {"mimeType": "text/html", "text": ""}}}
    S.append(Scenario("redirect-location-id", "id in redirect Location reused",
        [login(sec=0), redir,
         entry("GET", "https://app.example.com/api/orders/ORD-REDIR-991", hdr=bearer(), resp='{"ok":true}', sec=4, page="p2")],
        [not_in_jmx("ORD-REDIR-991<")]))   # the literal id must not be hardcoded in the consumer path

    # ---- cursor pagination: nextCursor server-issued -> correlate, not CSV ----
    S.append(Scenario("cursor-pagination", "cursor pagination",
        [login(sec=0),
         entry("GET", "https://app.example.com/api/feed", hdr=bearer(), resp='{"items":[],"nextCursor":"CUR-abc123xyz789"}', sec=2, page="p2"),
         entry("GET", "https://app.example.com/api/feed?cursor=CUR-abc123xyz789", hdr=bearer(), resp='{"items":[]}', sec=4, page="p2")],
        [not_param("nextCursor"), not_param("cursor")]))

    # ---- polling / parallel XHR: business endpoints retained ----
    poll = [login(sec=0)] + [entry("GET", "https://app.example.com/api/notifications/poll", hdr=bearer(),
                                    resp='{"n":0}', sec=2 + i, page="p2") for i in range(5)]
    S.append(Scenario("polling", "background polling retained", poll,
        [host_kept("app.example.com"), in_jmx("/api/notifications/poll")]))
    parallel = [login(sec=0)] + [entry("GET", f"https://app.example.com/api/widget{i}", hdr=bearer(),
                                        resp='{"w":%d}' % i, sec=2, page="p2") for i in range(4)]
    S.append(Scenario("parallel-xhr", "parallel XHRs retained", parallel,
        [in_jmx("/api/widget0"), in_jmx("/api/widget3")]))

    # ---- browser-generated idempotency GUID -> __UUID(), not a CSV column ----
    S.append(Scenario("browser-guid", "client idempotency key uuid not csv",
        [login(sec=0),
         entry("POST", "https://app.example.com/api/payments", hdr={"Idempotency-Key": "550e8400-e29b-41d4-a716-446655440000", **bearer()},
               body={"amount": "100.00"}, resp='{"paymentId":"P-1"}', sec=2, page="p2")],
        [not_param("Idempotency-Key")]))

    # ---- trace/request/timestamp values must not be parameterized ----
    for i, (k, v) in enumerate([("X-Request-Id", "req-abc-123-xyz"), ("X-Trace-Id", "trace-99887766"),
                                ("timestamp", "1704106800000")], 1):
        S.append(Scenario(f"noise-id-{i:02d}", "trace/request/timestamp not parameterized",
            [login(sec=0), entry("GET", f"https://app.example.com/api/data?{k.lower()}={v}", hdr={k: v, **bearer()}, resp='{"ok":true}', sec=2)],
            [not_param(k), not_param(k.lower())]))

    # ---- business CRUD workflows: create->retrieve, id correlated ----
    for i, ent in enumerate(["policy", "claim", "product", "account"], 1):
        server_id = f"{ent[:3].upper()}-{1000+i}"
        S.append(Scenario(f"crud-{ent}", f"{ent} create->retrieve",
            [login(sec=0),
             entry("POST", f"https://app.example.com/api/{ent}s", hdr=bearer(), body={"name": f"n{i}"},
                   resp=json.dumps({f"{ent}Id": server_id}), sec=2, page="p2"),
             entry("GET", f"https://app.example.com/api/{ent}s/{server_id}", hdr=bearer(), resp='{"ok":true}', sec=4, page="p3")],
            [not_in_jmx(f"{server_id}<")]))   # server id not hardcoded in the consumer

    # ---- numeric path id that is an existing selectable entity -> parameterize OR correlate, never hardcoded ----
    S.append(Scenario("existing-entity-path", "existing entity id in path",
        [login(sec=0),
         entry("GET", "https://app.example.com/api/products?q=phones", hdr=bearer(),
               resp='{"products":[{"productId":"PRD-4400"},{"productId":"PRD-4401"}]}', sec=2, page="p2"),
         entry("GET", "https://app.example.com/api/products/PRD-4400", hdr=bearer(), resp='{"ok":true}', sec=4, page="p3")],
        [not_in_jmx("/api/products/PRD-4400<")]))   # must be a variable, not a hardcoded catalog id

    # ---- additional analytics/ad/telemetry vendors (excluded) ----
    for i, (h, p) in enumerate([
        ("api.mixpanel.com", "/track"), ("api.segment.io", "/v1/t"), ("api2.amplitude.com", "/2/httpapi"),
        ("www.clarity.ms", "/collect"), ("o123.ingest.sentry.io", "/api/1/envelope/"),
        ("stats.g.doubleclick.net", "/g/collect"), ("bat.bing.com", "/action/0"),
    ], 1):
        S.append(Scenario(f"vendor-{i:02d}", "analytics/ad/telemetry vendor excluded",
            [login(sec=0), entry("POST", f"https://{h}{p}", resp='{"ok":1}', sec=2, page="p2"),
             entry("GET", "https://app.example.com/api/orders", hdr=bearer(), resp='{"orderId":"O-1"}', sec=3, page="p2")],
            [host_excluded(h), not_in_jmx(h)]))

    # ---- OAuth PKCE: client-minted state/nonce are NOT server secrets -> not correlated/parameterized ----
    S.append(Scenario("oauth-pkce", "oauth pkce client nonces",
        [entry("GET", "https://auth.example.com/authorize?state=st-abc123&nonce=nc-xyz789&code_challenge=cc-111", rmime="text/html", resp="<html></html>", sec=0),
         entry("POST", "https://auth.example.com/token", ctype="application/x-www-form-urlencoded",
               raw="grant_type=authorization_code&code=AUTHCODE-123", resp='{"access_token":"TKN-1"}', sec=2, page="p2")],
        [host_kept("auth.example.com"), not_param("state"), not_param("nonce")]))

    # ---- refresh token flow: refresh happens, business retained ----
    S.append(Scenario("refresh-token", "refresh token flow",
        [login(sec=0),
         entry("POST", "https://app.example.com/api/token", ctype="application/x-www-form-urlencoded",
               raw="grant_type=refresh_token&refresh_token=RFR-abc123", resp='{"access_token":"TKN-2"}', sec=2, page="p2"),
         entry("GET", "https://app.example.com/api/orders", hdr=bearer(), resp='{"orders":[]}', sec=4, page="p3")],
        [host_kept("app.example.com"), not_param("refresh_token")]))

    # ---- value repeated under different field names (same business input) ----
    S.append(Scenario("alias-fields", "same business value different names",
        [login(sec=0),
         entry("POST", "https://app.example.com/api/search", hdr=bearer(), body={"customerNumber": "CUST-55501"}, resp='{"r":[]}', sec=2, page="p2"),
         entry("GET", "https://app.example.com/api/orders?custNo=CUST-55501", hdr=bearer(), resp='{"orders":[]}', sec=4, page="p3")],
        [host_kept("app.example.com")]))

    # ---- report generation workflow ----
    S.append(Scenario("report-gen", "report generation",
        [login(sec=0),
         entry("POST", "https://app.example.com/api/reports/generate", hdr=bearer(), body={"type": "monthly", "month": "2024-01"}, resp='{"reportId":"RPT-8899"}', sec=2, page="p2"),
         entry("GET", "https://app.example.com/api/reports/RPT-8899", hdr=bearer(), resp='{"status":"ready"}', sec=6, page="p3")],
        [not_in_jmx("RPT-8899<")]))

    # ---- retries: same request 500 then 200; both are the same endpoint, kept ----
    S.append(Scenario("retry", "retry after 500",
        [login(sec=0),
         entry("GET", "https://app.example.com/api/inventory", hdr=bearer(), resp='{"e":1}', status=500, sec=2, page="p2"),
         entry("GET", "https://app.example.com/api/inventory", hdr=bearer(), resp='{"stock":5}', status=200, sec=3, page="p2")],
        [in_jmx("/api/inventory")]))

    # ---- long-poll / websocket-adjacent kept as business ----
    S.append(Scenario("long-poll", "long-poll endpoint kept",
        [login(sec=0), entry("GET", "https://app.example.com/api/events/stream", hdr=bearer(), resp='{"events":[]}', sec=2, page="p2")],
        [in_jmx("/api/events/stream")]))

    # ---- unknown third-party JSON API stays (UNKNOWN retained, not aggressively deleted) ----
    S.append(Scenario("unknown-thirdparty-json", "unknown third-party JSON retained",
        [login(sec=0), entry("GET", "https://some-unknown-partner.example.net/api/rates", hdr=bearer(), resp='{"rate":1.1}', sec=2, page="p2")],
        [host_kept("some-unknown-partner.example.net")]))

    # every scenario also implicitly gets universal invariants appended
    for sc in S:
        sc.checks = sc.checks + [no_unused_csv(), no_dup_csv(), no_tg_assertion()]
    return S


def run(verbose=False):
    scenarios = SCENARIOS()
    rows = []
    for sc in scenarios:
        try:
            ctx = build_ctx(sc.entries, sc.config)
        except Exception as ex:  # noqa: BLE001
            rows.append((sc.sid, sc.archetype, "BUILD-ERROR", False, str(ex)[:80]))
            continue
        for label, fn in sc.checks:
            try:
                ok, detail = fn(ctx)
            except Exception as ex:  # noqa: BLE001
                ok, detail = False, f"check-error: {ex}"
            rows.append((sc.sid, sc.archetype, label, ok, detail))
    return scenarios, rows


if __name__ == "__main__":
    scenarios, rows = run()
    fails = [r for r in rows if not r[3]]
    print(f"SYNTHETIC corpus: {len(scenarios)} scenarios, {len(rows)} checks, "
          f"{len(rows)-len(fails)} passed, {len(fails)} FAILED")
    if fails:
        print("\n=== DEFECT MATRIX (failed checks) ===")
        print(f"{'scenario':20} {'archetype':34} {'check':45} detail")
        for sid, arch, label, ok, detail in fails:
            print(f"{sid:20} {arch[:33]:34} {label[:44]:45} {detail}")
    else:
        print("All checks passed.")
