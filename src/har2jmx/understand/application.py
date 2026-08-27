"""Milestone 3 — application style understanding.

Evidence-gated detection of API style, server/app framework, SPA framework, and enterprise
platform, from the NormalizedCapture. General fingerprints only (headers, cookies, path/host
shapes, payload kind). Nothing is reported without concrete evidence in the capture.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from har2jmx.ir.normalized import BodyKind, NormalizedCapture, NormalizedRequest
from har2jmx.understand.models import Detection, EvidenceBag


@dataclass
class ApplicationProfile:
    api_styles: list[Detection] = field(default_factory=list)
    server_stack: list[Detection] = field(default_factory=list)
    spa_frameworks: list[Detection] = field(default_factory=list)
    enterprise_platforms: list[Detection] = field(default_factory=list)


def _rheader(req: NormalizedRequest, name: str) -> str:
    n = name.lower()
    for hn, hv in req.request.headers:
        if hn.lower() == n:
            return hv or ""
    return ""


def _respheader(req: NormalizedRequest, name: str) -> str:
    n = name.lower()
    for hn, hv in req.response.headers:
        if hn.lower() == n:
            return hv or ""
    return ""


def _cookie_names(req: NormalizedRequest) -> set[str]:
    names = {c.lower() for c, _ in req.request.cookies}
    names |= {c.lower() for c, _ in req.response.set_cookies}
    return names


_ODATA_RE = re.compile(r"(\$metadata|\$filter=|\$expand=|\$select=|\$orderby=|/odata/)", re.IGNORECASE)


def _detect_api_styles(cap: NormalizedCapture, bag: EvidenceBag) -> None:
    for req in cap.requests:
        path = req.request.path
        rkind, respkind = req.request.body.kind, req.response.body.kind

        if rkind == BodyKind.GRAPHQL:
            op = req.request.body.graphql_operation or "?"
            bag.add("GraphQL", f"GraphQL operation '{op}' in request body", "High")
        if rkind == BodyKind.SOAP or respkind == BodyKind.SOAP or _rheader(req, "soapaction"):
            ev = "SOAPAction header" if _rheader(req, "soapaction") else "SOAP envelope body"
            bag.add("SOAP", ev, "High")
        if _ODATA_RE.search(path) or _ODATA_RE.search(req.request.url):
            bag.add("OData", f"OData query option in '{path}'", "High")
        if "grpc-web" in (req.response.mime or "").lower() or "grpc-web" in _rheader(req, "content-type").lower():
            bag.add("gRPC-Web", "application/grpc-web content type", "High")
        if req.request.scheme in {"ws", "wss"} or _rheader(req, "upgrade").lower() == "websocket":
            bag.add("WebSocket", "WebSocket upgrade/scheme", "High")
        # REST: structured JSON over an API-ish path or a write method — the default modern style.
        if (rkind == BodyKind.JSON or respkind == BodyKind.JSON) and (
            re.search(r"/(api|rest|services?|v\d+)(/|$)", path, re.IGNORECASE) or req.method in {"POST", "PUT", "PATCH", "DELETE"}
        ):
            bag.add("REST", "JSON payload over API path / write method", "High")


def _detect_server_stack(cap: NormalizedCapture, bag: EvidenceBag) -> None:
    for req in cap.requests:
        server = _respheader(req, "server")
        powered = _respheader(req, "x-powered-by")
        cookies = _cookie_names(req)
        body_raw = (req.request.body.raw or "") + (req.response.body.raw or "")

        if "iis" in server.lower() or _respheader(req, "x-aspnet-version") or "asp.net" in powered.lower() \
                or "asp.net_sessionid" in cookies or "__requestverificationtoken" in body_raw.lower() \
                or "__viewstate" in body_raw.lower():
            ev = server or powered or "ASP.NET_SessionId / __VIEWSTATE"
            bag.add("ASP.NET", f"ASP.NET fingerprint ({ev})", "High")
        if "kestrel" in server.lower():
            bag.add("ASP.NET Core", "Server: Kestrel", "High")
        if "javax.faces.viewstate" in body_raw.lower() or "jakarta.faces" in body_raw.lower():
            bag.add("JSF", "javax.faces.ViewState present", "High")
        if "jsessionid" in cookies:
            bag.add("Java servlet", "JSESSIONID cookie", "Medium")
        if _respheader(req, "x-application-context") or re.search(r"/actuator(/|$)", req.request.path):
            bag.add("Spring", "Spring Actuator / X-Application-Context", "High")
        if "express" in powered.lower():
            bag.add("Express/Node", "X-Powered-By: Express", "High")
        if "php" in powered.lower() or "phpsessid" in cookies:
            bag.add("PHP", powered or "PHPSESSID cookie", "High")
        if "csrftoken" in cookies and "sessionid" in cookies:
            bag.add("Django", "csrftoken + sessionid cookies", "Medium")
        if _respheader(req, "x-runtime") and any(c.endswith("_session") for c in cookies):
            bag.add("Rails", "X-Runtime + _session cookie", "Medium")


_SPA_RULES: list[tuple[str, re.Pattern, str, str]] = [
    ("Next.js", re.compile(r"(__NEXT_DATA__|/_next/)", re.IGNORECASE), "Next.js marker (__NEXT_DATA__ / /_next/)", "High"),
    ("Nuxt", re.compile(r"(__NUXT__|/_nuxt/)", re.IGNORECASE), "Nuxt marker (__NUXT__ / /_nuxt/)", "High"),
    ("Angular", re.compile(r"(ng-version=|\bzone\.js|/polyfills[.-])", re.IGNORECASE), "Angular marker (ng-version / zone.js)", "Medium"),
    ("React", re.compile(r"(data-reactroot|react(?:-dom)?[.-][\w.]*\.js|/static/js/main\.[\w]+\.chunk)", re.IGNORECASE), "React marker", "Medium"),
    ("Vue", re.compile(r"(data-v-[0-9a-f]{6,}|vue(?:\.runtime)?[.-][\w.]*\.js)", re.IGNORECASE), "Vue marker", "Medium"),
]


def _detect_spa(cap: NormalizedCapture, bag: EvidenceBag) -> None:
    for req in cap.requests:
        hay = f"{req.request.path}\n{req.response.body.raw[:4000] if req.response.body.raw else ''}"
        for name, pattern, ev, conf in _SPA_RULES:
            if pattern.search(hay):
                bag.add(name, ev, conf)


# name, host regex (or None), path regex (or None), cookie substrings
_ENTERPRISE_RULES: list[tuple[str, re.Pattern | None, re.Pattern | None, tuple[str, ...]]] = [
    ("Salesforce", re.compile(r"force\.com|salesforce\.com|lightning\.force", re.I), re.compile(r"/services/data/", re.I), ("sid",)),
    ("SAP", re.compile(r"\bsap\b|hana\.ondemand|s4hana", re.I), re.compile(r"/sap/(opu/odata|bc)/", re.I), ("mysapsso2", "sap_sessionid")),
    ("ServiceNow", re.compile(r"service-now\.com|servicenow", re.I), re.compile(r"/api/now/", re.I), ("glide_",)),
    ("Guidewire", re.compile(r"guidewire", re.I), re.compile(r"/(pc|cc|bc)/service/", re.I), ()),
    ("Oracle ADF", re.compile(r"oraclecloud|oracle\.com", re.I), re.compile(r"(/adf/|_afrLoop=)", re.I), ()),
    ("Workday", re.compile(r"myworkday|workday\.com", re.I), None, ()),
    ("SuccessFactors", re.compile(r"successfactors", re.I), None, ()),
    ("Microsoft Dynamics", re.compile(r"dynamics\.com|crm\.dynamics", re.I), re.compile(r"/api/data/v\d", re.I), ()),
]


def _detect_enterprise(cap: NormalizedCapture, bag: EvidenceBag) -> None:
    for req in cap.requests:
        host, path = req.request.host or "", req.request.path
        cookies = _cookie_names(req)
        for name, host_re, path_re, cookie_subs in _ENTERPRISE_RULES:
            if host_re and host_re.search(host):
                bag.add(name, f"host matches '{host}'", "High")
            if path_re and path_re.search(path):
                bag.add(name, f"platform path '{path}'", "High")
            for sub in cookie_subs:
                if any(sub in c for c in cookies):
                    bag.add(name, f"platform cookie '{sub}*'", "High")


def detect_application(cap: NormalizedCapture) -> ApplicationProfile:
    api, server, spa, ent = EvidenceBag(), EvidenceBag(), EvidenceBag(), EvidenceBag()
    _detect_api_styles(cap, api)
    _detect_server_stack(cap, server)
    _detect_spa(cap, spa)
    _detect_enterprise(cap, ent)
    return ApplicationProfile(
        api_styles=api.results(),
        server_stack=server.results(),
        spa_frameworks=spa.results(),
        enterprise_platforms=ent.results(),
    )
