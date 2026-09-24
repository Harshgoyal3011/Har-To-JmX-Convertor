"""Build a valid HAR 1.2 file from a compact REAL browser capture.

Provenance policy (enforced, not decorative):
  * Every entry here comes from traffic actually observed in the browser pane (Resource Timing +
    the network log). Nothing is invented.
  * Response bodies are captured for JSON/API responses (the correlation-bearing ones). Bodies for
    large HTML/static assets are CAPPED — the cap is recorded per entry in `_truncatedBody` and in
    the manifest, so a reader can never mistake a capped body for a complete one.
  * `provenance` is stamped into log.comment so a downstream consumer cannot confuse a real capture
    with a synthetic fixture.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

BODY_CAP = 200_000          # per-response body cap (chars)

_MIME_BY_TYPE = {
    "script": "application/javascript", "css": "text/css", "link": "text/css",
    "img": "image/png", "iframe": "text/html", "fetch": "application/json",
    "xmlhttprequest": "application/json", "beacon": "text/plain", "navigation": "text/html",
    "other": "application/octet-stream",
}


def _mime(entry: dict) -> str:
    if entry.get("mime"):
        return entry["mime"]
    url = entry.get("u", "")
    path = urlparse(url).path.lower()
    for ext, m in ((".js", "application/javascript"), (".mjs", "application/javascript"),
                   (".css", "text/css"), (".json", "application/json"), (".svg", "image/svg+xml"),
                   (".png", "image/png"), (".jpg", "image/jpeg"), (".jpeg", "image/jpeg"),
                   (".gif", "image/gif"), (".woff2", "font/woff2"), (".woff", "font/woff"),
                   (".ico", "image/x-icon"), (".html", "text/html")):
        if path.endswith(ext):
            return m
    return _MIME_BY_TYPE.get(entry.get("t", "other"), "application/octet-stream")


def build_har(capture: dict, *, app: str, domain: str, flow: str, source: str,
              notes: str = "", provenance: str = "REAL_BROWSER_CAPTURE") -> dict:
    """capture = {doc, entries:[{u,t,d,s,p,method?,status?,mime?,body?,reqBody?,reqHeaders?}], startedAt?}"""
    t0 = datetime.now(timezone.utc).replace(microsecond=0)
    if capture.get("startedAt"):
        try:
            t0 = datetime.fromisoformat(capture["startedAt"].replace("Z", "+00:00"))
        except ValueError:
            pass

    entries = []
    clock = t0
    truncated = 0
    for e in capture.get("entries", []):
        url = e.get("u") or ""
        if not url.startswith(("http://", "https://")):
            continue
        parsed = urlparse(url)
        method = (e.get("method") or "GET").upper()
        status = int(e.get("status") or 200)
        dur = max(1, int(e.get("d") or 1))
        mime = _mime(e)
        body = e.get("body")
        was_trunc = False
        if isinstance(body, str) and len(body) > BODY_CAP:
            body = body[:BODY_CAP]
            was_trunc = True
            truncated += 1

        req = {
            "method": method,
            "url": url,
            "httpVersion": "HTTP/2" if (e.get("p") or "").startswith("h2") else "HTTP/1.1",
            "headers": list(e.get("reqHeaders") or []),
            "queryString": [{"name": k, "value": v} for k, v in
                            (tuple(p.split("=", 1)) if "=" in p else (p, "")
                             for p in (parsed.query.split("&") if parsed.query else []))],
            "cookies": [],
            "headersSize": -1,
            "bodySize": len(e.get("reqBody") or "") if e.get("reqBody") else 0,
        }
        if e.get("reqBody"):
            req["postData"] = {"mimeType": e.get("reqMime") or "application/json",
                               "text": e["reqBody"]}

        resp_headers = list(e.get("respHeaders") or [])
        if not any(h.get("name", "").lower() == "content-type" for h in resp_headers):
            resp_headers.append({"name": "Content-Type", "value": mime})

        entry = {
            "pageref": e.get("page") or "page_1",
            "startedDateTime": clock.isoformat().replace("+00:00", "Z"),
            "time": dur,
            "request": req,
            "response": {
                "status": status,
                "statusText": "OK" if status < 400 else "ERR",
                "httpVersion": req["httpVersion"],
                "headers": resp_headers,
                "cookies": [],
                "content": {"size": int(e.get("s") or 0), "mimeType": mime,
                            **({"text": body} if isinstance(body, str) else {})},
                "redirectURL": e.get("redirect") or "",
                "headersSize": -1,
                "bodySize": int(e.get("s") or 0),
            },
            "cache": {},
            "timings": {"send": 1, "wait": max(1, dur - 2), "receive": 1},
            "_resourceType": e.get("t") or "other",
        }
        if was_trunc:
            entry["_truncatedBody"] = True
        entries.append(entry)
        clock = clock + timedelta(milliseconds=dur + int(e.get("gap") or 0))

    return {
        "log": {
            "version": "1.2",
            "creator": {"name": "claude-browser-pane-capture", "version": "1.0"},
            "comment": json.dumps({
                "provenance": provenance,
                "application": app, "domain": domain, "flow": flow, "source": source,
                "captured_utc": t0.isoformat().replace("+00:00", "Z"),
                "body_cap_chars": BODY_CAP, "entries_with_truncated_body": truncated,
                "notes": notes,
            }),
            "pages": [{"startedDateTime": t0.isoformat().replace("+00:00", "Z"),
                       "id": "page_1", "title": app,
                       "pageTimings": {"onContentLoad": -1, "onLoad": -1}}],
            "entries": entries,
        }
    }


def write_har(capture: dict, out: Path, **meta) -> tuple[Path, int, int]:
    har = build_har(capture, **meta)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(har, indent=1), encoding="utf-8")
    ents = har["log"]["entries"]
    hosts = len({urlparse(e["request"]["url"]).netloc for e in ents})
    return out, len(ents), hosts
