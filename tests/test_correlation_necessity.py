"""Correlation necessity gate: high-recall discovery, minimal required emission."""
from __future__ import annotations

import json
import re
from pathlib import Path

from har2jmx.correlate import (
    CorrelationDecision,
    ExtractorType,
    RejectionKind,
    apply_necessity_gate,
    discover_correlation_candidates,
)
from har2jmx.emit import build_jmx_xml
from har2jmx.emit.validate import validate_plan
from har2jmx.engine import analyze
from har2jmx.lineage import build_lineage
from har2jmx.webreport import build_web_summary

FIX = Path(__file__).parent / "fixtures"

CLIENT = "aaaaaaaa-bbbb-cccc-dddd-eeeeffff0001"
APP = "bbbbbbbb-cccc-dddd-eeee-ffff00001111"
REDIRECT = "https://app.example.com/oauth2/callback"
AUTH_URL = "https://login.example.com/oauth2/v2.0/authorize"
TOKEN = "eyJhbGciOiJub25lIn0.eyJzdWIiOiJ1MSJ9.sigsigsig"
CSRF = "csrfTokenValue99abxxZZ"
TXN = "TXN-991122334455"
CREATED = "CUST-created-88421"
SELECTED = "CUST-existing-10019"
TX = "StatePropertiesTx99abxxZZ"
CONT = f"https://login.example.com/te/oauth2/authorize?tx={TX}"
PATH2 = "/te/oauth2/authorize"
DEAD = "deadTokenNeverUsed99"


def _e(method, url, status=200, resp="{}", body=None, mime="application/json", headers=None, form=None):
    req_h = [{"name": "Accept", "value": "application/json"}]
    for k, v in (headers or {}).items():
        req_h.append({"name": k, "value": v})
    e = {
        "startedDateTime": "2026-01-01T10:00:00.000Z", "time": 20,
        "request": {"method": method, "url": url, "headers": req_h, "cookies": []},
        "response": {
            "status": status,
            "headers": [{"name": "Content-Type", "value": mime}],
            "content": {"mimeType": mime, "text": resp},
        },
    }
    if body is not None:
        e["request"]["postData"] = {"mimeType": "application/json", "text": body}
        e["request"]["headers"].append({"name": "Content-Type", "value": "application/json"})
    if form is not None:
        e["request"]["postData"] = {
            "mimeType": "application/x-www-form-urlencoded",
            "text": form,
        }
        e["request"]["headers"].append({"name": "Content-Type", "value": "application/x-www-form-urlencoded"})
    return e


def _har(entries):
    return json.dumps({"log": {"version": "1.2", "entries": entries}}).encode()


def _vals(res):
    return {c.value for c in res.correlations}


def _vars(res):
    return {c.variable for c in res.correlations}


def test_csrf_is_correlated():
    r = analyze((FIX / "sample_csrf.har").read_bytes())
    assert "RequestVerificationToken" in _vars(r)
    x = build_jmx_xml(r).decode()
    tok = next(c for c in r.correlations if c.variable == "RequestVerificationToken")
    assert f"${{{tok.variable}}}" in x
    assert tok.value not in x or tok.expression in x


def test_access_token_is_correlated():
    r = analyze((FIX / "sample_bearer.har").read_bytes())
    assert "accessToken" in _vars(r)
    x = build_jmx_xml(r).decode()
    val = next(c.value for c in r.correlations if c.variable == "accessToken")
    assert "${accessToken}" in x
    assert f"Bearer {val}" not in x


def test_authorization_code_is_correlated():
    r = analyze((FIX / "sample_oauth.har").read_bytes())
    code = next(c for c in r.correlations if c.variable == "code")
    assert code.from_redirect
    x = build_jmx_xml(r).decode()
    assert "${code}" in x
    assert code.value not in x


def test_transaction_id_correlated_when_consumed():
    r = analyze(_har([
        _e("POST", "https://api.example.com/payments", 201,
           json.dumps({"txnId": TXN})),
        _e("GET", f"https://api.example.com/payments/{TXN}/status"),
    ]))
    assert TXN in _vals(r)
    x = build_jmx_xml(r).decode()
    var = next(c.variable for c in r.correlations if c.value == TXN)
    assert f"${{{var}}}" in x
    assert f"payments/{TXN}" not in x
    assert validate_plan(r, x) == []


def test_created_entity_id_is_correlated():
    r = analyze(_har([
        _e("POST", "https://api.example.com/customers", 201,
           json.dumps({"id": CREATED, "name": "Ada"})),
        _e("GET", f"https://api.example.com/customers/{CREATED}"),
    ]))
    assert CREATED in _vals(r)


def test_unused_generated_token_is_not_correlated():
    r = analyze((FIX / "sample_bearer.har").read_bytes())
    assert "refreshToken" not in _vars(r)
    html = (
        "<html><input type='hidden' name='csrf' value='" + CSRF + "'/></html>"
    )
    r2 = analyze(_har([
        _e("GET", "https://app.example.com/login", resp=html, mime="text/html"),
        _e("POST", "https://app.example.com/login",
           resp=json.dumps({"access_token": TOKEN, "unused": DEAD}),
           body=json.dumps({"csrf": CSRF})),
        _e("GET", "https://api.example.com/me",
           headers={"Authorization": f"Bearer {TOKEN}"}),
    ]))
    assert DEAD not in _vals(r2)
    assert TOKEN in _vals(r2) or CSRF in _vals(r2)


def test_static_client_id_is_hardcoded():
    r = analyze(_oidc_har())
    assert CLIENT not in _vals(r)
    kinds = {x.kind for x in r.correlation_audit.rejected if x.decision.value == CLIENT}
    assert kinds & {RejectionKind.CONFIGURATION, RejectionKind.PROTOCOL_METADATA} or CLIENT not in {
        c.value for c in r.correlation_audit.candidates
    }


def test_static_redirect_url_is_hardcoded():
    r = analyze(_oidc_har())
    assert REDIRECT not in _vals(r)


def test_oidc_capability_metadata_is_hardcoded():
    r = analyze(_oidc_har())
    assert "query" not in _vals(r)
    assert "code" not in _vals(r) or any(
        c.variable == "code" and c.value != "code" for c in r.correlations
    )
    rejected_vals = {x.decision.value for x in r.correlation_audit.rejected
                     if x.kind in {RejectionKind.PROTOCOL_METADATA, RejectionKind.CONFIGURATION}}
    assert "query" in rejected_vals or "query" not in {c.value for c in r.correlation_audit.candidates}


def test_static_path_and_url_are_hardcoded():
    r = analyze(_oidc_har())
    assert AUTH_URL not in _vals(r)
    assert "/oauth2/v2.0/authorize" not in _vals(r)


def test_selected_existing_entity_is_parameterized_not_correlated():
    r = analyze((FIX / "sample_naming.har").read_bytes())
    product = "SKU-88231-ALPHA"
    assert product not in _vals(r)
    ds = {v for d in r.parameterization.datasets for row in d.rows for v in row.values()}
    assert product in ds


def test_runtime_created_entity_is_correlated():
    r = analyze((FIX / "sample_naming.har").read_bytes())
    assert "ORD-5501-2026" in _vals(r)


def test_covered_child_correlation_is_superseded():
    r = analyze(_har([
        _e("POST", "https://login.example.com/selfAsserted", 200,
           resp=json.dumps({"url": CONT, "path": PATH2, "tx": TX})),
        _e("POST", "https://app.example.com/resume", 200, resp="{}",
           body=json.dumps({"redirect": CONT, "path": PATH2, "tx": TX})),
    ]))
    assert CONT in _vals(r)
    assert PATH2 not in _vals(r)
    assert TX not in _vals(r)
    assert r.correlation_audit.count(RejectionKind.SUPERSEDED) >= 1


def test_zero_consumer_extractor_is_not_emitted():
    r = analyze((FIX / "sample_flow.har").read_bytes())
    dead = CorrelationDecision(
        variable="ghost", value="ghost-value", producer_index=0,
        producer_location="response.body:ghost", extractor=ExtractorType.JSON,
        expression="$..ghost", consumers=[], confidence="High",
    )
    audit = apply_necessity_gate(r.capture, build_lineage(r.capture), r.classification, [dead])
    assert audit.count(RejectionKind.NO_CONSUMER) == 1
    assert audit.emitted == []


def test_ui_reports_candidates_vs_required():
    r = analyze(_oidc_har())
    summary = build_web_summary(r, "rid", {})
    audit = summary["correlationAudit"]
    assert audit["candidates"] == len(r.correlation_audit.candidates)
    assert audit["required"] == len(summary["correlations"])
    assert audit["candidates"] >= audit["required"]
    assert summary["metrics"]["correlations"] == len(summary["correlations"])


def test_discovery_recall_is_unchanged_for_necessary_tokens():
    """Gate must not hide CSRF/token/code from *candidates* — only from emission of config."""
    r = analyze((FIX / "sample_csrf.har").read_bytes())
    from har2jmx.classify import classify_capture, classify_values
    from har2jmx.ir.build import build_capture
    from har2jmx.lineage import build_lineage
    cap = build_capture((FIX / "sample_csrf.har").read_bytes())
    classify_capture(cap)
    lin = build_lineage(cap)
    cls = classify_values(cap, lin)
    cands = discover_correlation_candidates(cap, cls, lin)
    assert any(c.variable == "RequestVerificationToken" for c in cands)
    assert any(c.variable == "RequestVerificationToken" for c in r.correlations)


def _b2c_settings():
    return {
        "appId": APP,
        "groupName": "B2C_1_signupsignin",
        "redirectParam": "redirect_uri",
        "redirectUrl": REDIRECT,
        "clientId": CLIENT,
        "getcustomizationCode": "GetCustomization",
        "X_CSRF_TOKEN": CSRF,
        "path": "/contoso.onmicrosoft.com/B2C_1_signupsignin/oauth2/v2.0/authorize",
        "path2": "/contoso.onmicrosoft.com/B2C_1_signupsignin/api/SelfAsserted",
        "tx": TX,
        "url": CONT,
        "remoteResource": "https://contoso.b2clogin.com/static/bundle.js",
        "hosts": {"tenant": "contoso.b2clogin.com"},
        "response_modes_supported": ["query", "fragment", "form_post"],
        "response_types_supported": ["code", "id_token", "code id_token"],
    }


def _b2c_har(html_wrapped: bool = False):
    settings = _b2c_settings()
    if html_wrapped:
        body = "<html><script>var SETTINGS = " + json.dumps(settings) + ";</script></html>"
        mime = "text/html"
    else:
        body = json.dumps(settings)
        mime = "application/json"
    path2 = settings["path2"]
    return _har([
        _e("GET", "https://contoso.b2clogin.com/contoso.onmicrosoft.com/v2.0/.well-known/openid-configuration",
           resp=json.dumps({
               "issuer": "https://contoso.b2clogin.com/",
               "authorization_endpoint": AUTH_URL,
               "token_endpoint": "https://contoso.b2clogin.com/oauth2/v2.0/token",
               "jwks_uri": "https://contoso.b2clogin.com/discovery/v2.0/keys",
               "response_types_supported": settings["response_types_supported"],
               "response_modes_supported": settings["response_modes_supported"],
           })),
        _e("GET", "https://contoso.b2clogin.com/contoso.onmicrosoft.com/B2C_1_signupsignin/api/CombinedSigninAndSignup/unified",
           resp=body, mime=mime),
        _e("POST", f"https://contoso.b2clogin.com{path2}?tx={TX}",
           form=(
               f"request_type=RESPONSE&tx={TX}&redirect_uri={REDIRECT}"
               f"&redirectUrl={REDIRECT}&appId={APP}&groupName=B2C_1_signupsignin"
               f"&getcustomizationCode=GetCustomization&url={CONT}"
               f"&path={settings['path']}"
           ),
           headers={"X-CSRF-TOKEN": CSRF}),
        _e("GET",
           f"{AUTH_URL}?client_id={CLIENT}&redirect_uri={REDIRECT}"
           f"&response_type=id_token&response_mode=query"),
    ])


def _jmx_extractors(xml: str) -> set[str]:
    return set(re.findall(r'referenceNames">([^<]+)<', xml)) | set(
        re.findall(r'RegexExtractor\.refname">([^<]+)<', xml)
    )


def test_b2c_settings_config_is_not_required_correlation():
    r = analyze(_b2c_har())
    x = build_jmx_xml(r).decode()
    ui = build_web_summary(r, "b2c", {}, jmx_xml=x)
    ui_vars = {c["variable"] for c in ui["correlations"]}
    extractors = _jmx_extractors(x)
    assert ui_vars - {"AUTH"} <= extractors | {c.variable for c in r.correlations
                                               if c.extractor.value == "cookie_manager"}
    banned_vals = {APP, CLIENT, REDIRECT, "B2C_1_signupsignin", "redirect_uri", "GetCustomization",
                   "/contoso.onmicrosoft.com/B2C_1_signupsignin/oauth2/v2.0/authorize",
                   "/contoso.onmicrosoft.com/B2C_1_signupsignin/api/SelfAsserted",
                   CONT, "query", "id_token"}
    assert not (_vals(r) & banned_vals)
    for var in _vars(r):
        if var in extractors:
            assert f"${{{var}}}" in x
    # config values must not be extractor names
    for name in ("appId", "groupName", "redirectParam", "redirectUrl", "clientId",
                 "getcustomizationCode", "path", "path2", "url"):
        assert name not in extractors
        assert name not in ui_vars
    assert "X_CSRF_TOKEN" in _vars(r)
    assert TX in _vals(r)
    assert "X_CSRF_TOKEN" in extractors and "X_CSRF_TOKEN" in ui_vars
    assert next(c.variable for c in r.correlations if c.value == TX) in extractors


def test_b2c_html_settings_json_is_still_config():
    r = analyze(_b2c_har(html_wrapped=True))
    assert CLIENT not in _vals(r)
    assert APP not in _vals(r)
    assert CSRF in _vals(r) or any(c.variable == "X_CSRF_TOKEN" for c in r.correlations)


def test_path2_without_consumer_is_not_emitted():
    r = analyze(_b2c_har())
    path2 = "/contoso.onmicrosoft.com/B2C_1_signupsignin/api/SelfAsserted"
    assert path2 not in _vals(r)
    cands = [c for c in r.correlation_audit.candidates if c.value == path2]
    if cands:
        assert r.correlation_audit.count(RejectionKind.NO_CONSUMER) >= 1 or cands[0] not in r.correlations


def test_config_candidate_with_consumer_is_rejected_by_gate():
    r = analyze(_b2c_har())
    assert CLIENT in {c.value for c in r.correlation_audit.candidates} or CLIENT not in _vals(r)
    if CLIENT in {c.value for c in r.correlation_audit.candidates}:
        kinds = {x.kind for x in r.correlation_audit.rejected if x.decision.value == CLIENT}
        assert RejectionKind.CONFIGURATION in kinds
        assert CLIENT not in _vals(r)
    x = build_jmx_xml(r).decode()
    assert "clientId" not in _jmx_extractors(x)


def test_ui_required_list_matches_jmx_extractors():
    r = analyze(_b2c_har())
    x = build_jmx_xml(r).decode()
    ui = build_web_summary(r, "b2c", {}, jmx_xml=x)
    ui_vars = {c["variable"] for c in ui["correlations"]}
    extractors = _jmx_extractors(x)
    cookie = {c.variable for c in r.correlations if c.extractor.value == "cookie_manager"}
    assert ui_vars <= extractors | cookie
    assert ui["metrics"]["correlations"] == len(ui["correlations"])


def _oidc_har():
    meta = {
        "issuer": "https://login.example.com/",
        "authorization_endpoint": AUTH_URL,
        "token_endpoint": "https://login.example.com/oauth2/v2.0/token",
        "jwks_uri": "https://login.example.com/discovery/v2.0/keys",
        "response_types_supported": ["code", "id_token", "token"],
        "response_modes_supported": ["query", "fragment", "form_post"],
        "client_id": CLIENT,
        "application_id": APP,
        "redirect_uri": REDIRECT,
    }
    return _har([
        _e("GET", "https://login.example.com/.well-known/openid-configuration",
           resp=json.dumps(meta)),
        _e("GET",
           f"{AUTH_URL}?client_id={CLIENT}&redirect_uri={REDIRECT}"
           f"&response_type=code&response_mode=query&appid={APP}"),
    ])
