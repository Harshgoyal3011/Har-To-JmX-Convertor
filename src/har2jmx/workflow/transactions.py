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
    return bool(_ID_SEG_RE.match(seg))


def _entity_noun(segments: list[str]) -> str:
    for seg in reversed(segments):
        low = seg.lower()
        if not low or _is_id_seg(low) or _VERSION_RE.match(low):
            continue
        if low in _API_WORDS or low in _VERB_WORDS:
            continue
        return _titleize(_singularize(low))
    # fall back to any non-id segment even if it's an API word
    for seg in reversed(segments):
        if seg and not _is_id_seg(seg.lower()) and not _VERSION_RE.match(seg.lower()):
            return _titleize(_singularize(seg.lower()))
    return ""


def _has_search_signal(req: NormalizedRequest) -> bool:
    keys = {k.lower() for k, _ in req.request.query}
    return bool(keys & _SEARCH_QUERY_KEYS)


def _name_transaction(req: NormalizedRequest) -> tuple[str, str]:
    """Return (name, category) for an anchor request, from generic endpoint semantics."""
    segs = [s.lower() for s in req.request.path_segments]
    noun = _entity_noun(req.request.path_segments) or "Request"
    method = req.method

    # GraphQL: name from the operation (all requests share one endpoint).
    if req.request.body.kind == BodyKind.GRAPHQL and req.request.body.graphql_operation:
        op = req.request.body.graphql_operation
        low = op.lower()
        action = any(low.startswith(v) for v in ("create", "add", "update", "edit", "delete",
                                                 "remove", "submit", "set", "save"))
        return _titleize(op), ("Business Action" if action else "Business View")

    def has(*words: str) -> bool:
        return any(s in words for s in segs)

    # Authentication
    if has("logout", "signout", "logoff"):
        return "Logout", "Authentication"
    is_login_submit = has("login", "signin", "logon", "authenticate", "sso") or \
        (method in {"POST", "PUT"} and has("token", "authorize", "oauth"))
    if is_login_submit:
        return "Login", "Authentication"
    if req.classification.role == RequestRole.AUTH:
        # auth-tagged but not a login submit (e.g. GET /auth/me, /session, /userinfo)
        if noun.lower() in {"me", "self", "whoami", "session", "userinfo", "user", "profile"}:
            return "Session", "Authentication"
        return f"{noun} Session", "Authentication"

    # Explicit action verbs in the path
    if has("search", "find", "lookup", "query", "browse"):
        return f"{noun} Search", "Business View"
    if has("checkout"):
        return "Checkout", "Business Action"
    if has("pay", "payment"):
        return "Payment", "Business Action"
    if has("upload", "import"):
        return f"Upload {noun}", "Business Action"
    if has("export", "download", "report", "print"):
        return f"Export {noun}", "Business View"
    if has("create", "new", "add"):
        return f"Create {noun}", "Business Action"
    if has("update", "edit", "modify", "save"):
        return f"Update {noun}", "Business Action"
    if has("delete", "remove"):
        return f"Delete {noun}", "Business Action"
    if has("submit", "file", "confirm"):
        return f"Submit {noun}", "Business Action"

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
        return f"Open {noun}", "Business View"
    if "html" in (req.response.mime or "").lower():
        return f"Open {noun}" if noun != "Request" else "Open Page", "Navigation"
    return f"View {noun}", "Business View"


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
    used_names: dict[str, int] = {}
    for g in merged:
        candidates = [r for r in g if not r.classification.excluded] or g
        anchor = max(candidates, key=_anchor_priority)
        name, category = _name_transaction(anchor)

        # keep names stable + unique when the same action repeats
        if name in used_names:
            used_names[name] += 1
            display = f"{name} ({used_names[name]})"
        else:
            used_names[name] = 1
            display = name

        for r in g:
            r.context.transaction = display

        transactions.append(Transaction(
            name=display,
            category=category,
            anchor_index=anchor.index,
            request_indices=[r.index for r in g],
            business_indices=[r.index for r in g if not r.classification.excluded],
        ))

    return transactions
