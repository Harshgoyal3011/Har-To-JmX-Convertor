"""Milestone 3 — authentication understanding.

Evidence-gated detection of the auth mechanism(s) in a capture: HTTP auth schemes, OAuth2/OIDC,
SAML, IdP vendors, cookie-based sessions, and token refresh. General patterns only; every finding
carries evidence. No mechanism is claimed without it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from har2jmx.ir.normalized import NormalizedCapture, NormalizedRequest
from har2jmx.understand.models import Detection, EvidenceBag

_JWT_RE = re.compile(r"^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$")
_SESSION_COOKIE_RE = re.compile(
    r"^(jsessionid|sessionid|session|asp\.net_sessionid|phpsessid|connect\.sid|sid|"
    r"\.aspxauth|auth_?token|access_?token|csrf.?token|xsrf.?token)$",
    re.IGNORECASE,
)


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


def _params(req: NormalizedRequest) -> dict[str, str]:
    d: dict[str, str] = {}
    for k, v in req.request.query:
        d.setdefault(k.lower(), v)
    for k, v in req.request.body.form:
        d.setdefault(k.lower(), v)
    return d


@dataclass
class AuthProfile:
    mechanisms: list[Detection] = field(default_factory=list)
    token_refresh: bool = False
    primary: str | None = None


def _detect_http_schemes(req: NormalizedRequest, bag: EvidenceBag) -> None:
    authz = _rheader(req, "authorization")
    if authz:
        scheme = authz.split(" ", 1)[0].lower()
        if scheme == "basic":
            bag.add("HTTP Basic", "Authorization: Basic", "High")
        elif scheme == "digest":
            bag.add("HTTP Digest", "Authorization: Digest", "High")
        elif scheme == "ntlm":
            bag.add("NTLM", "Authorization: NTLM", "High")
        elif scheme == "negotiate":
            bag.add("Kerberos/Negotiate (SPNEGO)", "Authorization: Negotiate", "High")
        elif scheme == "bearer":
            token = authz.split(" ", 1)[1].strip() if " " in authz else ""
            if _JWT_RE.match(token):
                bag.add("Bearer/JWT", "Authorization: Bearer <JWT>", "High")
            else:
                bag.add("Bearer/JWT", "Authorization: Bearer <token>", "High")
    www = _respheader(req, "www-authenticate").lower()
    if www:
        if "negotiate" in www:
            bag.add("Kerberos/Negotiate (SPNEGO)", "WWW-Authenticate: Negotiate", "High")
        if "ntlm" in www:
            bag.add("NTLM", "WWW-Authenticate: NTLM", "High")
        if www.startswith("digest") or " digest" in www:
            bag.add("HTTP Digest", "WWW-Authenticate: Digest", "High")
        if www.startswith("basic") or " basic" in www:
            bag.add("HTTP Basic", "WWW-Authenticate: Basic", "Medium")


def _detect_oauth_oidc(req: NormalizedRequest, bag: EvidenceBag) -> bool:
    """Returns True if this request evidences a token refresh."""
    path, host = req.request.path, (req.request.host or "")
    params = _params(req)
    refresh = False

    if re.search(r"/(oauth2?|connect)/(authorize|token)|/oauth/token|/token(/|$)", path, re.IGNORECASE):
        bag.add("OAuth2", f"OAuth2/OIDC endpoint '{path}'", "High")
    if "grant_type" in params or "response_type" in params:
        bag.add("OAuth2", f"OAuth2 param ({', '.join(k for k in ('grant_type','response_type') if k in params)})", "High")
    if params.get("grant_type", "").lower() == "refresh_token" or "refresh_token" in params:
        refresh = True
    if "openid" in (params.get("scope", "").lower()) or "id_token" in params.get("response_type", "").lower():
        bag.add("OpenID Connect", "OIDC scope/response_type", "High")
    if re.search(r"/\.well-known/openid-configuration", path, re.IGNORECASE):
        bag.add("OpenID Connect", "OIDC discovery document", "High")
    # id_token in a JSON token response
    if req.response.body.json is not None and isinstance(req.response.body.json, dict):
        keys = {k.lower() for k in req.response.body.json.keys()}
        if "id_token" in keys:
            bag.add("OpenID Connect", "id_token in token response", "High")
        if "refresh_token" in keys:
            refresh = True

    # IdP vendors
    if re.search(r"login\.microsoftonline\.com|sts\.windows\.net|login\.windows\.net", host, re.I):
        bag.add("Azure AD / Entra ID", f"Microsoft identity host '{host}'", "High")
    if re.search(r"\.okta(?:preview)?\.com", host, re.I):
        bag.add("Okta", f"Okta host '{host}'", "High")
    if re.search(r"\.auth0\.com", host, re.I):
        bag.add("Auth0", f"Auth0 host '{host}'", "High")
    if re.search(r"/adfs/", path, re.I):
        bag.add("ADFS", "ADFS endpoint path", "High")
    if re.search(r"/(auth/)?realms/", path, re.I) or "keycloak" in host.lower():
        bag.add("Keycloak", "Keycloak realms endpoint", "High")
    return refresh


def _detect_saml(req: NormalizedRequest, bag: EvidenceBag) -> None:
    params = _params(req)
    if "samlrequest" in params or "samlresponse" in params:
        bag.add("SAML", "SAMLRequest/SAMLResponse parameter", "High")
    elif re.search(r"/saml2?(/|$)", req.request.path, re.IGNORECASE):
        bag.add("SAML", f"SAML endpoint '{req.request.path}'", "Medium")
    body = (req.request.body.raw or "")[:2000]
    if "urn:oasis:names:tc:SAML" in body:
        bag.add("SAML", "SAML assertion namespace in body", "High")


def _detect_cookie_session(cap: NormalizedCapture, bag: EvidenceBag) -> None:
    # A session cookie set by the server AND sent back on a later request → cookie-based session.
    produced: dict[str, int] = {}
    for req in cap.requests:
        for name, _ in req.response.set_cookies:
            if _SESSION_COOKIE_RE.match(name) and name.lower() not in produced:
                produced[name.lower()] = req.index
    for req in cap.requests:
        for name, _ in req.request.cookies:
            low = name.lower()
            if low in produced and req.index > produced[low]:
                bag.add("Cookie session", f"session cookie '{name}' set then replayed", "High")
                break


def detect_auth(cap: NormalizedCapture) -> AuthProfile:
    bag = EvidenceBag()
    token_refresh = False
    for req in cap.requests:
        _detect_http_schemes(req, bag)
        if _detect_oauth_oidc(req, bag):
            token_refresh = True
        _detect_saml(req, bag)
    _detect_cookie_session(cap, bag)

    mechanisms = bag.results()
    # Primary = the strongest, preferring token/federation over simple session/basic.
    priority = ["Bearer/JWT", "OAuth2", "OpenID Connect", "SAML", "Kerberos/Negotiate (SPNEGO)",
                "NTLM", "Cookie session", "HTTP Digest", "HTTP Basic"]
    primary = None
    for name in priority:
        if any(m.name == name for m in mechanisms):
            primary = name
            break
    if primary is None and mechanisms:
        primary = mechanisms[0].name

    return AuthProfile(mechanisms=mechanisms, token_refresh=token_refresh, primary=primary)
