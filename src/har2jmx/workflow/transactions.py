"""Milestone 4 — workflow / transaction discovery.

Groups requests into **user actions**, not per-API. Supporting calls (validation, AJAX, dependent
fetches for the same action) nest inside their parent transaction. Names are business-meaningful,
concise, and derived generically from endpoint semantics — no app-specific keyword tables.

Boundary evidence (in priority): page navigation (pageref change), then a think-time gap between
requests. Each group's name comes from its most significant *anchor* request (an action write >
search > open/view > navigation), never from a trailing static or beacon.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

from har2jmx.ir.normalized import BodyKind, NormalizedCapture, NormalizedRequest, RequestRole

_THINK_GAP_MS = 2500  # a pause longer than this between requests suggests a new user action

_API_WORDS = {"api", "rest", "service", "services", "ws", "rpc", "gql", "graphql", "odata", "web", "app"}
_VERB_WORDS = {
    "search", "find", "lookup", "query", "list", "browse", "create", "new", "add", "save",
    "update", "edit", "modify", "delete", "remove", "submit", "file", "open", "view", "get",
    "pay", "payment", "checkout", "confirm", "login", "signin", "logon", "authenticate",
    "logout", "signout", "upload", "import", "download", "export", "report", "print",
    # action verbs common to enterprise flows
    "initiate", "verify", "approve", "reject", "cancel", "activate", "deactivate", "process",
    "apply", "register", "enroll", "book", "reserve", "acknowledge", "complete", "validate",
    "generate", "calculate", "compute", "run", "execute", "send", "dispatch", "notify",
    "sync", "reset", "refresh", "assign", "transfer",
}


def _av(template: str, category: str):
    return lambda noun: (template.format(n=noun).strip(), category)


# Action verb (as the TERMINAL path segment) → transaction name. Matching the terminal segment (not
# any mid-path segment) avoids naming GET /payment/{id}/receipt as "Payment".
_ACTION_TERMINALS = {
    "checkout": _av("Checkout", "Business Action"),
    "pay": _av("Payment", "Business Action"), "payment": _av("Payment", "Business Action"),
    "search": _av("{n} Search", "Business View"), "find": _av("{n} Search", "Business View"),
    "lookup": _av("{n} Search", "Business View"), "query": _av("{n} Search", "Business View"),
    "browse": _av("{n} Search", "Business View"),
    "initiate": _av("Initiate {n}", "Business Action"), "confirm": _av("Confirm {n}", "Business Action"),
    "verify": _av("Verify {n}", "Business Action"), "validate": _av("Validate {n}", "Business Action"),
    "approve": _av("Approve {n}", "Business Action"), "reject": _av("Reject {n}", "Business Action"),
    "cancel": _av("Cancel {n}", "Business Action"), "submit": _av("Submit {n}", "Business Action"),
    "activate": _av("Activate {n}", "Business Action"), "deactivate": _av("Deactivate {n}", "Business Action"),
    "process": _av("Process {n}", "Business Action"), "apply": _av("Apply {n}", "Business Action"),
    "register": _av("Register {n}", "Business Action"), "enroll": _av("Enroll {n}", "Business Action"),
    "book": _av("Book {n}", "Business Action"), "reserve": _av("Reserve {n}", "Business Action"),
    "acknowledge": _av("Acknowledge {n}", "Business Action"), "complete": _av("Complete {n}", "Business Action"),
    "upload": _av("Upload {n}", "Business Action"), "import": _av("Import {n}", "Business Action"),
    "export": _av("Export {n}", "Business View"), "download": _av("Export {n}", "Business View"),
    "report": _av("Export {n}", "Business View"), "print": _av("Export {n}", "Business View"),
    "create": _av("Create {n}", "Business Action"), "add": _av("Create {n}", "Business Action"),
    "new": _av("Create {n}", "Business Action"),
    "update": _av("Update {n}", "Business Action"), "edit": _av("Update {n}", "Business Action"),
    "modify": _av("Update {n}", "Business Action"),
    "delete": _av("Delete {n}", "Business Action"), "remove": _av("Delete {n}", "Business Action"),
    "generate": _av("Generate {n}", "Business Action"), "calculate": _av("Calculate {n}", "Business Action"),
    "compute": _av("Calculate {n}", "Business Action"), "run": _av("Run {n}", "Business Action"),
    "execute": _av("Run {n}", "Business Action"), "send": _av("Send {n}", "Business Action"),
    "dispatch": _av("Dispatch {n}", "Business Action"), "notify": _av("Notify {n}", "Business Action"),
    "sync": _av("Sync {n}", "Business Action"), "reset": _av("Reset {n}", "Business Action"),
    "assign": _av("Assign {n}", "Business Action"), "transfer": _av("Transfer {n}", "Business Action"),
}
_SEARCH_QUERY_KEYS = {"q", "query", "search", "keyword", "term", "filter", "name", "text"}
_ID_SEG_RE = re.compile(r"^(?:\d+|[0-9a-fA-F]{8,}|[0-9a-fA-F-]{16,})$")
_VERSION_RE = re.compile(r"^v\d+$", re.IGNORECASE)
_CAMEL_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


@dataclass
class Transaction:
    name: str
    category: str                 # Authentication | Business Action | Business View | Navigation | Other
    anchor_index: int
    request_indices: list[int] = field(default_factory=list)   # every request in this action
    business_indices: list[int] = field(default_factory=list)  # non-excluded subset


# ---------------------------------------------------------------- naming helpers

def _singularize(word: str) -> str:
    w = word
    if len(w) > 3 and w.endswith("ies"):
        return w[:-3] + "y"
    if len(w) > 3 and w.endswith(("ses", "xes", "zes", "ches", "shes")):
        return w[:-2]
    if len(w) > 2 and w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w


def _titleize(token: str) -> str:
    parts = _CAMEL_RE.sub(" ", token).replace("-", " ").replace("_", " ").split()
    return " ".join(p[:1].upper() + p[1:] for p in parts if p)


def _is_id_seg(seg: str) -> bool:
    s = seg.lower()
    if _ID_SEG_RE.match(s):
        return True
    # instance identifiers mix letters and digits (PAT-9001, ORD-5501-2026, APPT-7788, 2862)
    return any(ch.isdigit() for ch in s)


def _meaningful(low: str) -> bool:
    return bool(low) and not _is_id_seg(low) and not _VERSION_RE.match(low) \
        and low not in _API_WORDS and low not in _VERB_WORDS


def _entity_noun(segments: list[str]) -> str:
    """Singular business noun for the resource (Patient, Order) — for create/update/open."""
    for seg in reversed(segments):
        if _meaningful(seg.lower()):
            return _titleize(_singularize(seg.lower()))
    for seg in reversed(segments):
        if seg and not _is_id_seg(seg.lower()) and not _VERSION_RE.match(seg.lower()):
            return _titleize(_singularize(seg.lower()))
    return ""


def _collection_noun(segments: list[str]) -> str:
    """The resource segment as captured (usually plural: Patients, Orders) — for list/view."""
    for seg in reversed(segments):
        if _meaningful(seg.lower()):
            return _titleize(seg)
    return _entity_noun(segments) or "Items"


_SOAP_BODY_OP_RE = re.compile(r"<(?:[\w.-]+:)?Body[^>]*>\s*<(?:[\w.-]+:)?([A-Za-z_][\w.-]*)", re.IGNORECASE)


def _soap_operation(req: NormalizedRequest) -> str | None:
    for name, value in req.request.headers:
        if name.lower() == "soapaction" and value:
            action = value.strip().strip('"').rsplit("/", 1)[-1].rsplit("#", 1)[-1]
            if action:
                return action
    m = _SOAP_BODY_OP_RE.search(req.request.body.raw or "")
    return m.group(1) if m else None


def _has_search_signal(req: NormalizedRequest) -> bool:
    keys = {k.lower() for k, _ in req.request.query}
    return bool(keys & _SEARCH_QUERY_KEYS)


def _name_transaction(req: NormalizedRequest) -> tuple[str, str]:
    """Return (name, category) for an anchor request, from generic endpoint semantics."""
    segs = [s.lower() for s in req.request.path_segments]
    noun = _entity_noun(req.request.path_segments) or "Request"
    method = req.method

    # SOAP: name from the operation (SOAPAction header, else the first body element).
    if req.request.body.kind == BodyKind.SOAP:
        op = _soap_operation(req)
        if op:
            low = op.lower()
            if low.startswith(("login", "logon", "authenticate")):
                return "Login", "Authentication"
            if low.startswith(("logout", "signout")):
                return "Logout", "Authentication"
            action = any(low.startswith(v) for v in ("create", "add", "update", "edit", "delete",
                                                     "remove", "submit", "set", "save", "insert", "post"))
            return _titleize(op), ("Business Action" if action else "Business View")

    # GraphQL: name from the operation (all requests share one endpoint).
    if req.request.body.kind == BodyKind.GRAPHQL and req.request.body.graphql_operation:
        op = req.request.body.graphql_operation
        low = op.lower()
        action = any(low.startswith(v) for v in ("create", "add", "update", "edit", "delete",
                                                 "remove", "submit", "set", "save"))
        return _titleize(op), ("Business Action" if action else "Business View")

    def has(*words: str) -> bool:
        return any(s in words for s in segs)

    # a multipart request with file parts is a file upload
    if req.request.body.files:
        return f"Upload {noun}", "Business Action"

    # Authentication
    if has("logout", "signout", "logoff"):
        return "Logout", "Authentication"
    is_login_submit = has("login", "signin", "logon", "authenticate", "sso") or \
        (method in {"POST", "PUT"} and has("token", "authorize", "oauth", "auth", "session", "connect"))
    if is_login_submit:
        return "Login", "Authentication"
    if req.classification.role == RequestRole.AUTH:
        # auth-tagged but not a login submit (e.g. GET /auth/me, /session, /userinfo)
        if noun.lower() in {"me", "self", "whoami", "session", "userinfo", "user", "profile"}:
            return "Session", "Authentication"
        return f"{noun} Session", "Authentication"

    # Action from the TERMINAL path segment (the last non-id/non-version/non-api segment, INCLUDING
    # verbs): /transfers/initiate -> Initiate Transfer   |   /payment/{id}/receipt -> View Receipt
    terminal = next((s for s in reversed(segs)
                     if s and not _is_id_seg(s) and not _VERSION_RE.match(s) and s not in _API_WORDS), "")
    if terminal in _ACTION_TERMINALS:
        return _ACTION_TERMINALS[terminal](noun)

    # Method-driven fallback
    if method in {"POST"}:
        # POST to a collection (no trailing id) reads as a create; with search params, a search.
        if _has_search_signal(req):
            return f"{noun} Search", "Business View"
        return f"Create {noun}", "Business Action"
    if method in {"PUT", "PATCH"}:
        return f"Update {noun}", "Business Action"
    if method == "DELETE":
        return f"Delete {noun}", "Business Action"

    # GET
    if _has_search_signal(req):
        return f"{noun} Search", "Business View"
    if req.request.path_segments and _is_id_seg(req.request.path_segments[-1].lower()):
        return f"Open {noun}", "Business View"          # detail: single record
    if "html" in (req.response.mime or "").lower():
        return f"Open {_collection_noun(req.request.path_segments)}" if noun != "Request" else "Open Page", "Navigation"
    return f"View {_collection_noun(req.request.path_segments)}", "Business View"   # list: collection


# ---------------------------------------------------------------- grouping

def _parse_iso(s: str) -> datetime | None:
    if not s:
        return None
    try:
        t = re.sub(r"Z$", "", s.strip())
        t = re.sub(r"[+-]\d{2}:\d{2}$", "", t)
        return datetime.fromisoformat(t[:26])
    except (ValueError, TypeError):
        return None


def _gap_ms(prev: NormalizedRequest, curr: NormalizedRequest) -> float | None:
    a, b = _parse_iso(prev.context.started), _parse_iso(curr.context.started)
    if a is None or b is None:
        return None
    return (b - a).total_seconds() * 1000.0


def _is_boundary(prev: NormalizedRequest, curr: NormalizedRequest) -> bool:
    p_ref, c_ref = prev.context.pageref, curr.context.pageref
    if p_ref and c_ref and p_ref != c_ref:
        return True
    gap = _gap_ms(prev, curr)
    if gap is not None and gap > _THINK_GAP_MS:
        return True
    return False


def _anchor_priority(req: NormalizedRequest) -> int:
    """Higher = more likely to be the request that names the user action."""
    role = req.classification.role
    if req.classification.excluded:
        return -1
    if role == RequestRole.AUTH:
        # the auth *submit* (a write) is a better anchor than the auth page load (a GET)
        return 110 if req.method in {"POST", "PUT", "PATCH"} else 100
    if req.method in {"POST", "PUT", "PATCH", "DELETE"}:
        return 80
    if _has_search_signal(req):
        return 70
    if req.request.path_segments and _is_id_seg(req.request.path_segments[-1].lower()):
        return 60
    if "html" in (req.response.mime or "").lower():
        return 40  # navigation document
    if role == RequestRole.BUSINESS:
        return 50
    return 10


def discover_transactions(cap: NormalizedCapture) -> list[Transaction]:
    """Group the capture into user-action transactions and annotate each request."""
    if not cap.requests:
        return []

    # 1) split into raw groups on navigation / think-time boundaries
    groups: list[list[NormalizedRequest]] = [[cap.requests[0]]]
    for prev, curr in zip(cap.requests, cap.requests[1:]):
        if _is_boundary(prev, curr):
            groups.append([curr])
        else:
            groups[-1].append(curr)

    # 2) merge groups that contain no business-relevant request into the previous one
    merged: list[list[NormalizedRequest]] = []
    for g in groups:
        has_business = any(not r.classification.excluded for r in g)
        if not has_business and merged:
            merged[-1].extend(g)
        else:
            merged.append(g)

    # 3) name each group from its best anchor and annotate requests
    transactions: list[Transaction] = []
    for g in merged:
        candidates = [r for r in g if not r.classification.excluded] or g
        anchor = max(candidates, key=_anchor_priority)
        name, category = _name_transaction(anchor)
        transactions.append(Transaction(
            name=name,
            category=category,
            anchor_index=anchor.index,
            request_indices=[r.index for r in g],
            business_indices=[r.index for r in g if not r.classification.excluded],
        ))

    _label_launch(cap, transactions)     # rename the landing action BEFORE de-duplicating names
    _dedupe_names(cap, transactions)
    return transactions


def _dedupe_names(cap: NormalizedCapture, transactions: list[Transaction]) -> None:
    """Suffix repeated names ('Login (2)') and stamp the final name on each request."""
    counts: dict[str, int] = {}
    for t in transactions:
        counts[t.name] = counts.get(t.name, 0) + 1
        if counts[t.name] > 1:
            t.name = f"{t.name} ({counts[t.name]})"
        for i in t.request_indices:
            cap.requests[i].context.transaction = t.name


_HOME_SEGMENTS = {"home", "index", "landing", "welcome", "app", "portal", "dashboard", "main", "default"}


def _label_launch(cap: NormalizedCapture, transactions: list[Transaction]) -> None:
    """The first user action, when it's the app landing/home page load, reads as 'Launch Application'
    to a stakeholder — much clearer than 'Open Home' or a raw path."""
    if not transactions:
        return
    first = transactions[0]
    # scan the first user action for a landing/home page navigation (may be a supporting request,
    # not the anchor — the anchor can be a data call fired by the page).
    for i in first.request_indices:
        rq = cap.requests[i]
        if rq.method != "GET" or "html" not in (rq.response.mime or "").lower():
            continue
        segs = {s.lower() for s in rq.request.path_segments}
        if not segs or rq.request.path in ("/", "") or bool(segs & _HOME_SEGMENTS):
            first.name = "Launch Application"
            first.category = "Navigation"
            for j in first.request_indices:
                cap.requests[j].context.transaction = "Launch Application"
            return
