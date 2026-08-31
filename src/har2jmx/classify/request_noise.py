"""Milestone 2 — request noise classification.

Tags every request in a NormalizedCapture with a role (static / telemetry / auth / business /
polling / upload / download) and an exclusion decision, using **general vendor and shape patterns**
only — no application-, domain-, or endpoint-specific rules. Requests are never deleted here; noise
is tagged and reported so every downstream decision stays auditable against the full capture.

Design rules honored:
- A request is excluded only when it does not contribute to business replay (telemetry, static
  assets, CORS preflight, HEAD probes).
- Static resources are tagged so later stages never treat them as correlation producers/consumers.
- Auth traffic is business-relevant (needed for replay) and is NOT excluded.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from har2jmx.ir.normalized import BodyKind, NormalizedCapture, NormalizedRequest, RequestRole
from har2jmx.patterns import STATIC_EXTENSIONS

# --- Telemetry / RUM / analytics vendors (general, vendor-level, not app-specific) ---
TELEMETRY_HOST_RE = re.compile(
    r"(?:"
    r"google-analytics|googletagmanager|analytics\.google|g\.doubleclick|doubleclick\.net|"
    r"stats\.g\.doubleclick|"                                    # Google
    r"omtrdc\.net|demdex\.net|2o7\.net|adobedc\.net|\.sc\.omtrdc|"  # Adobe Analytics
    r"go-mpulse\.net|akstat\.io|\.mpstat\.us|mpulse|boomerang|"  # Akamai mPulse / boomerang
    r"nr-data\.net|newrelic\.com|bam\.nr-data|"                  # New Relic
    r"dynatrace|ruxit\.com|dynatrace-managed|"                   # Dynatrace RUM
    r"eum-appdynamics|appdynamics|"                              # AppDynamics RUM
    r"mixpanel\.com|segment\.(?:io|com)|amplitude\.com|heap(?:analytics)?\.com|"
    r"hotjar\.com|mouseflow\.com|fullstory\.com|clarity\.ms|"    # session/analytics
    r"browser-intake-datadoghq|datadoghq\.com/api/v\d/rum|"      # Datadog RUM
    r"ingest\.sentry\.io|sentry_key|"                            # Sentry
    r"facebook\.com/tr|connect\.facebook\.net|bat\.bing\.com|px\.ads\.linkedin"  # ad pixels
    r")",
    re.IGNORECASE,
)
# Beacon/telemetry endpoints by path shape (kept specific to avoid catching business endpoints).
TELEMETRY_PATH_RE = re.compile(
    r"(?:/eum/|/rum(?:/|\b)|/beacon(?:s)?(?:/|\b)|/telemetry/|/csp-report|/__rum|"
    r"/collect(?:/|\?|$)|/i/adsct|/g/collect|/b/ss/|/mpulse|/boomerang)",
    re.IGNORECASE,
)

# --- Static resource paths (general) ---
STATIC_PATH_RE = re.compile(
    r"/(?:static|assets?|content|css|js|scripts?|fonts?|images?|img|media|vendor|dist|build|"
    r"webjars|_next/static|node_modules)/",
    re.IGNORECASE,
)
_STATIC_MIME_HINTS = ("text/css", "javascript", "image/", "font/", "audio/", "video/", "application/font")

# --- Auth (business-relevant, general OIDC/SAML/form vocabulary) ---
AUTH_SEGMENT_RE = re.compile(
    r"^(?:login|signin|sign-in|logon|logoff|logout|signout|sign-out|authenticate|auth|authorize|"
    r"authorization|token|sso|saml|saml2|openid|oauth|oauth2|connect|adfs|session|refresh)$",
    re.IGNORECASE,
)

# --- Download (general) ---
DOWNLOAD_SEGMENT_RE = re.compile(
    r"^(?:download|export|report|reports|pdf|excel|xlsx|csv|print|attachment|attachments|file|files)$",
    re.IGNORECASE,
)
UPLOAD_SEGMENT_RE = re.compile(r"^(?:upload|uploads|import|attach|attachment|attachments)$", re.IGNORECASE)

# --- API shape (general) ---
API_PATH_RE = re.compile(r"/(?:api|rest|graphql|gql|odata|services?|ws|rpc|v\d+)(?:/|$)", re.IGNORECASE)

_POLLING_MIN_HITS = 4  # same method+path seen at least this many times → polling candidate


@dataclass
class ClassificationSummary:
    total: int = 0
    by_role: Counter = field(default_factory=Counter)
    excluded: int = 0
    business: int = 0

    @property
    def excluded_pct(self) -> float:
        return round(100 * self.excluded / self.total, 1) if self.total else 0.0


def _suffix(path: str) -> str:
    name = PurePosixPath(path).name
    return PurePosixPath(name).suffix.lower()


def _has_content_disposition_attachment(req: NormalizedRequest) -> bool:
    for name, value in req.response.headers:
        if name.lower() == "content-disposition" and "attachment" in (value or "").lower():
            return True
    return False


def _is_static(req: NormalizedRequest) -> tuple[bool, str]:
    suffix = _suffix(req.request.path)
    if suffix in STATIC_EXTENSIONS:
        return True, f"static file extension '{suffix}'"
    if STATIC_PATH_RE.search(req.request.path):
        return True, "static resource path"
    mime = (req.response.mime or "").lower()
    if any(h in mime for h in _STATIC_MIME_HINTS):
        # Guard: a JS/CSS/image response that also sets cookies or is JSON-shaped may carry state.
        if not req.response.set_cookies:
            return True, f"static response type '{mime.split(';')[0]}'"
    return False, ""


def _is_telemetry(req: NormalizedRequest) -> tuple[bool, str]:
    host = req.request.host or ""
    if TELEMETRY_HOST_RE.search(host):
        return True, f"known telemetry/RUM vendor host '{host}'"
    if TELEMETRY_PATH_RE.search(req.request.path):
        return True, "beacon/telemetry endpoint path"
    return False, ""


def _is_auth(req: NormalizedRequest) -> bool:
    return any(AUTH_SEGMENT_RE.match(seg) for seg in req.request.path_segments)


_REFRESH_GRANT_RE = re.compile(r"grant_type[\"'\s:=]+refresh_token", re.IGNORECASE)


def is_token_refresh(req: NormalizedRequest) -> bool:
    """A token-refresh request exchanges a refresh token for a fresh access token.

    Detected structurally (never by endpoint name): an OAuth2 ``grant_type=refresh_token`` write, or
    a write that carries a ``refresh_token`` field. This is machinery triggered by expiry, not a user
    action, so it must not name/anchor a transaction the way an interactive login does.
    """
    if req.method not in {"POST", "PUT"}:
        return False
    b = req.request.body
    kv = {str(k).lower(): str(v).lower() for k, v in (b.form or [])}
    if kv.get("grant_type") == "refresh_token" or "refresh_token" in kv:
        return True
    if isinstance(b.json, dict):
        jl = {str(k).lower(): str(v).lower() for k, v in b.json.items()}
        if jl.get("grant_type") == "refresh_token" or "refresh_token" in jl:
            return True
    return bool(b.raw and _REFRESH_GRANT_RE.search(b.raw))


def _looks_business(req: NormalizedRequest) -> bool:
    if req.method not in {"GET", "HEAD"}:
        return True
    if API_PATH_RE.search(req.request.path):
        return True
    if req.request.body.is_structured or req.response.body.is_structured:
        return True
    mime = (req.response.mime or "").lower()
    return "json" in mime or "xml" in mime


def classify_request(req: NormalizedRequest) -> None:
    """Classify a single request (everything except capture-level polling). Mutates in place."""
    c = req.classification
    c.reasons = []

    # 1. Protocol control — never business replay content.
    if req.method == "OPTIONS":
        c.role = RequestRole.UNKNOWN
        c.excluded = True
        c.exclusion_reason = "CORS preflight (OPTIONS)"
        c.reasons.append(c.exclusion_reason)
        return
    if req.method == "HEAD":
        c.role = RequestRole.UNKNOWN
        c.excluded = True
        c.exclusion_reason = "HEAD probe"
        c.reasons.append(c.exclusion_reason)
        return

    # 2. Telemetry / RUM / analytics — excluded (does not contribute to business replay).
    is_tel, tel_reason = _is_telemetry(req)
    if is_tel:
        c.role = RequestRole.TELEMETRY
        c.telemetry_candidate = True
        c.excluded = True
        c.exclusion_reason = tel_reason
        c.reasons.append(tel_reason)
        return

    # 3. Static assets — excluded from scripting; never a correlation producer/consumer.
    is_static, static_reason = _is_static(req)
    if is_static:
        c.role = RequestRole.STATIC
        c.static_candidate = True
        c.excluded = True
        c.exclusion_reason = static_reason
        c.reasons.append(static_reason)
        return

    # 4. Auth — business-relevant, retained.
    if _is_auth(req):
        c.role = RequestRole.AUTH
        c.auth_candidate = True
        c.business_candidate = True
        c.reasons.append("authentication vocabulary in path")
        return

    # 5. Upload / download (still business, but tagged for special handling downstream).
    if req.request.body.kind == BodyKind.MULTIPART or any(
        UPLOAD_SEGMENT_RE.match(s) for s in req.request.path_segments
    ):
        c.role = RequestRole.UPLOAD
        c.upload_candidate = True
        c.business_candidate = True
        c.reasons.append("multipart body / upload path")
        return
    if _has_content_disposition_attachment(req) or any(
        DOWNLOAD_SEGMENT_RE.match(s) for s in req.request.path_segments
    ):
        c.role = RequestRole.DOWNLOAD
        c.download_candidate = True
        c.business_candidate = True
        c.reasons.append("download/export path or attachment response")
        return

    # 6. Business (default for application/API traffic).
    if _looks_business(req):
        c.role = RequestRole.BUSINESS
        c.business_candidate = True
        c.reasons.append("application/API request (structured payload, API path, or write method)")
        return

    # 7. Otherwise unknown — kept, flagged for review, never silently wired downstream.
    c.role = RequestRole.UNKNOWN
    c.reasons.append("no strong signal; retained for manual review")


def _mark_polling(capture: NormalizedCapture) -> None:
    """Flag requests whose method+path repeats often as polling candidates (capture-level)."""
    groups: dict[tuple[str, str], list[NormalizedRequest]] = defaultdict(list)
    for req in capture.requests:
        if req.classification.excluded:
            continue
        groups[(req.method, req.request.path)].append(req)
    for (method, path), members in groups.items():
        if len(members) >= _POLLING_MIN_HITS:
            for req in members:
                c = req.classification
                c.polling_candidate = True
                if f"repeated {len(members)}× (polling)" not in c.reasons:
                    c.reasons.append(f"repeated {len(members)}× (polling)")
                # Polling is business-relevant but usually reduced, not excluded — only reclassify
                # role when it wasn't a stronger business subtype.
                if c.role in {RequestRole.BUSINESS, RequestRole.UNKNOWN}:
                    c.role = RequestRole.POLLING


def _mark_superseded_auth_failures(capture: NormalizedCapture) -> None:
    """Drop a recorded auth-expiry failure that a token refresh + retry already recovered.

    A capture of a refresh cycle contains the doomed call (HTTP 401/403 on an expired access token)
    right before the refresh and the successful retry of the *same* endpoint. Replayed as-is that
    sampler fails every iteration and pollutes the results, yet it carries no unique business intent —
    its successful retry represents the real call. When (and only when) a 401/403 is followed by a
    token-refresh request and then a 2xx/3xx retry of the same method+path, exclude the failed
    attempt so the load script has no built-in failure. Precise by construction: without both the
    refresh and the matching successful retry, nothing is dropped.
    """
    reqs = capture.requests
    for i, req in enumerate(reqs):
        if req.classification.excluded or (req.status or 0) not in (401, 403):
            continue
        refresh_at = next((j for j in range(i + 1, len(reqs)) if is_token_refresh(reqs[j])), None)
        if refresh_at is None:
            continue
        retry = next((k for k in range(refresh_at + 1, len(reqs))
                      if reqs[k].method == req.method
                      and reqs[k].request.path == req.request.path
                      and 200 <= (reqs[k].status or 0) < 400), None)
        if retry is None:
            continue
        c = req.classification
        c.excluded = True
        c.exclusion_reason = "pre-refresh auth failure (401/403) superseded by token refresh + retry"
        c.reasons.append(c.exclusion_reason)


def classify_capture(capture: NormalizedCapture) -> ClassificationSummary:
    """Classify every request in the capture. Mutates classifications in place; returns a summary."""
    for req in capture.requests:
        classify_request(req)
    _mark_polling(capture)
    _mark_superseded_auth_failures(capture)

    summary = ClassificationSummary(total=capture.count)
    for req in capture.requests:
        summary.by_role[req.classification.role.value] += 1
        if req.classification.excluded:
            summary.excluded += 1
        if req.classification.business_candidate and not req.classification.excluded:
            summary.business += 1
    return summary


def build_request_classification_report(capture: NormalizedCapture) -> str:
    """Human-readable RequestClassificationReport (markdown). Classifies if not already done."""
    already = any(r.classification.reasons for r in capture.requests)
    summary = _summarize(capture) if already else classify_capture(capture)
    lines: list[str] = []
    lines.append("# Request Classification Report\n")
    lines.append(f"**Total requests:** {summary.total}  ")
    lines.append(f"**Excluded from scripting:** {summary.excluded} ({summary.excluded_pct}%)  ")
    lines.append(f"**Business-relevant:** {summary.business}\n")
    lines.append("## Roles\n")
    lines.append("| Role | Count |")
    lines.append("|---|---|")
    for role, count in summary.by_role.most_common():
        lines.append(f"| {role} | {count} |")
    lines.append("\n## Excluded requests\n")
    lines.append("| # | Request | Role | Reason |")
    lines.append("|---|---|---|---|")
    any_excluded = False
    for req in capture.requests:
        if req.classification.excluded:
            any_excluded = True
            lines.append(
                f"| {req.index} | {req.label()} | {req.classification.role.value} | "
                f"{req.classification.exclusion_reason} |"
            )
    if not any_excluded:
        lines.append("| — | (none) | — | — |")
    return "\n".join(lines) + "\n"


def _summarize(capture: NormalizedCapture) -> ClassificationSummary:
    summary = ClassificationSummary(total=capture.count)
    for req in capture.requests:
        summary.by_role[req.classification.role.value] += 1
        if req.classification.excluded:
            summary.excluded += 1
        if req.classification.business_candidate and not req.classification.excluded:
            summary.business += 1
    return summary
