"""RC-1 — conservative beacon/ad-RTB/telemetry noise classification.

Proven fire-and-forget beacon families (from the real-HAR audit) must be excluded and must NOT become
samplers, transaction anchors, or correlation candidates. Genuine business POSTs (incl. ambiguous ones
like /api/track) and unknown non-beacon requests must be retained.
"""
from __future__ import annotations

import json

from har2jmx.classify.request_noise import _is_beacon
from har2jmx.emit import build_jmx_xml
from har2jmx.engine import analyze
from har2jmx.ir.build import build_capture


def _e(method, url, *, body=None, ctype="application/json", resp="{}", sec=0, page="p1"):
    ent = {"pageref": page, "startedDateTime": f"2024-01-01T10:00:{sec:02d}.000Z", "time": 20,
           "request": {"method": method, "url": url, "cookies": [],
                       "headers": [{"name": "Content-Type", "value": ctype},
                                   {"name": "Authorization", "value": "Bearer TKN-1"}]},
           "response": {"status": 200, "headers": [{"name": "Content-Type", "value": "application/json"}],
                        "content": {"mimeType": "application/json", "text": resp}}}
    if body is not None:
        ent["request"]["postData"] = {"mimeType": ctype, "text": json.dumps(body) if ctype.endswith("json") else body}
    return ent


def _analyze(entries):
    return analyze(json.dumps({"log": {"version": "1.2", "entries": entries}}).encode())


# proven beacon families from the audit (host or path shape)
BEACONS = [
    ("POST", "https://hbopenbid.pubmatic.com/translator?operId=101"),      # PubMatic ad exchange
    ("POST", "https://grid-bidder.criteo.com/openrtb_2_5/pbjs/auction"),   # Criteo RTB
    ("POST", "https://mp.4dex.io/prebid"),                                 # prebid
    ("POST", "https://o6787.ingest.us.sentry.io/api/4511/envelope/"),      # Sentry regional ingest
    ("POST", "https://collector-pxabc.perimeterx.net/api/v2/collector"),   # PerimeterX
    ("GET",  "https://www.example.com/cdn-cgi/challenge-platform/scripts"),  # Cloudflare challenge
    ("POST", "https://marlin-2.docker.com/docker.marlin.v1.LogService/LogEvent"),  # Docker telemetry
    ("GET",  "https://sync.example-ssp.com/setuid?bidder=ix"),             # cookie-sync
]


def test_each_beacon_family_is_classified_noise():
    for method, url in BEACONS:
        cap = build_capture(json.dumps({"log": {"version": "1.2", "entries": [_e(method, url)]}}).encode())
        req = cap.requests[0]
        ok, reason = _is_beacon(req)
        assert ok, f"NOT detected as beacon: {method} {url}"
        assert reason


def test_beacons_excluded_and_not_in_jmx_while_business_retained():
    entries = [
        _e("POST", "https://app.example.com/api/orders", body={"item": "widget"},
           resp='{"orderId":"ORD-77"}', sec=0),
        _e("GET", "https://app.example.com/api/orders/ORD-77", resp='{"orderId":"ORD-77"}', sec=1),
    ] + [_e(m, u, sec=2) for m, u in BEACONS]
    res = _analyze(entries)
    kept = {r.request.host for r in res.capture.requests if not r.classification.excluded}
    excl = {r.request.host for r in res.capture.requests if r.classification.excluded}
    assert "app.example.com" in kept                              # business retained
    for _m, u in BEACONS:
        host = u.split("/")[2]
        if "cdn-cgi" not in u:                                    # cdn-cgi is same-host path-shape
            assert host in excl, f"{host} should be excluded"
    xml = build_jmx_xml(res).decode()
    for frag in ("pubmatic", "criteo", "4dex", "sentry", "perimeterx", "LogService", "/setuid", "/openrtb"):
        assert frag not in xml, f"beacon leaked into JMX: {frag}"


def test_beacon_never_anchors_a_transaction_or_correlates():
    # a beacon interleaved with a business action must not name/anchor the transaction
    entries = [
        _e("POST", "https://hbopenbid.pubmatic.com/translator", body={"imp": 1}, sec=0),
        _e("GET", "https://app.example.com/api/products?q=laptop",
           resp='{"products":[{"productId":"P-1"}]}', sec=1),
    ]
    res = _analyze(entries)
    for t in res.transactions:
        a = res.capture.requests[t.anchor_index]
        assert "pubmatic" not in a.request.host, f"beacon anchored transaction '{t.name}'"
    # no correlation should be sourced from the beacon
    assert not any("pubmatic" in c.reason.lower() for c in res.correlations)


def test_business_posts_not_false_excluded():
    # ambiguous-but-business endpoints must stay in the workload
    for url in ["https://app.example.com/api/track?orderId=ORD-9",     # order tracking (not analytics)
                "https://app.example.com/api/orders",
                "https://app.example.com/api/logs/audit",              # business audit log
                "https://app.example.com/api/metrics/dashboard"]:      # business metrics view
        cap = build_capture(json.dumps({"log": {"version": "1.2", "entries": [_e("POST", url, body={"x": 1})]}}).encode())
        ok, _ = _is_beacon(cap.requests[0])
        assert not ok, f"business endpoint wrongly flagged as beacon: {url}"


def test_unknown_non_beacon_request_is_retained_for_review():
    # an unknown third-party POST that is NOT a proven beacon must not be aggressively removed
    res = _analyze([_e("POST", "https://api.some-unknown-partner.net/v1/quote", body={"amount": 100},
                       resp='{"rate":1.1}')])
    kept = {r.request.host for r in res.capture.requests if not r.classification.excluded}
    assert "api.some-unknown-partner.net" in kept
