"""Build the normalized IR from a HAR — the single HAR→domain translation for the new pipeline.

Milestone 1. Reuses the low-level parsing primitives in ``har.reader`` (so raw HAR parsing lives
in exactly one place) and adds structure: body typing (json/form/multipart/graphql/soap/xml),
response Set-Cookie parsing, redirect detection, and capture context (sequence/timing/page).

Unlike the legacy ``har.samplers.build_script_ir``, this keeps **every** entry — static and
telemetry requests are classified later (Milestone 2), not filtered here.
"""

from __future__ import annotations

import json as _json
from typing import Any
from urllib.parse import urlparse

from har2jmx.har.reader import (
    cookie_pairs,
    decode_response_text,
    header_pairs,
    header_value,
    post_files,
    post_pairs,
    read_har,
)
from har2jmx.ir.normalized import (
    Body,
    BodyKind,
    HttpRequest,
    HttpResponse,
    NormalizedCapture,
    NormalizedRequest,
    RequestContext,
)


def _looks_json(text: str) -> bool:
    head = text.lstrip()[:1]
    return head in {"{", "["}


def _graphql_operation(parsed: Any) -> str | None:
    """Return the operation name if a parsed JSON body is a GraphQL request, else None."""
    def _is_gql(obj: dict) -> bool:
        return "query" in obj and isinstance(obj.get("query"), str)

    if isinstance(parsed, dict) and _is_gql(parsed):
        return str(parsed.get("operationName") or "")
    if isinstance(parsed, list) and parsed and isinstance(parsed[0], dict) and _is_gql(parsed[0]):
        return str(parsed[0].get("operationName") or "")
    return None


def _build_request_body(params: list[tuple[str, str]], text: str, mime: str,
                        files: list[tuple[str, str, str]] | None = None) -> Body:
    m = (mime or "").lower()
    if "multipart/form-data" in m:
        return Body(kind=BodyKind.MULTIPART, mime=mime, raw=text, form=params, files=files or [])
    if params or "x-www-form-urlencoded" in m:
        return Body(kind=BodyKind.FORM, mime=mime, raw=text, form=params)
    return _build_text_body(text, mime)


def _build_text_body(text: str, mime: str) -> Body:
    if not text:
        return Body(kind=BodyKind.NONE, mime=mime)
    m = (mime or "").lower()
    lstripped = text.lstrip()

    if "graphql" in m or "json" in m or _looks_json(text):
        parsed: Any = None
        try:
            parsed = _json.loads(text)
        except (ValueError, TypeError):
            parsed = None
        op = _graphql_operation(parsed) if parsed is not None else None
        if op is not None:
            return Body(kind=BodyKind.GRAPHQL, mime=mime, raw=text, json=parsed, graphql_operation=op)
        if parsed is not None or "json" in m:
            return Body(kind=BodyKind.JSON, mime=mime, raw=text, json=parsed)

    if "xml" in m or lstripped.startswith("<"):
        if "soap" in m or "<soap" in lstripped[:400].lower() or "envelope" in lstripped[:200].lower():
            return Body(kind=BodyKind.SOAP, mime=mime, raw=text)
        return Body(kind=BodyKind.XML, mime=mime, raw=text)

    return Body(kind=BodyKind.TEXT, mime=mime, raw=text)


def _parse_set_cookies(response_headers: list[tuple[str, str]]) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for name, value in response_headers:
        if name.lower() == "set-cookie" and value:
            cookie_name, _, rest = value.partition("=")
            cookie_value = rest.split(";", 1)[0].strip()
            if cookie_name.strip():
                out.append((cookie_name.strip(), cookie_value))
    return out


def _initiator(entry: dict[str, Any]) -> str:
    init = entry.get("_initiator")
    if isinstance(init, dict):
        return str(init.get("type") or init.get("url") or "")
    if isinstance(init, str):
        return init
    return ""


def build_capture(har: dict[str, Any] | bytes) -> NormalizedCapture:
    """Normalize a HAR (raw bytes or an already-parsed dict) into a NormalizedCapture."""
    if isinstance(har, (bytes, bytearray)):
        har = read_har(bytes(har))

    log = har.get("log", {}) if isinstance(har, dict) else {}
    pages = {
        page.get("id", ""): (page.get("title") or page.get("id") or "")
        for page in log.get("pages", []) or []
    }
    entries: list[dict[str, Any]] = log.get("entries", []) or []

    requests: list[NormalizedRequest] = []
    for index, entry in enumerate(entries):
        req = entry.get("request", {}) or {}
        resp = entry.get("response", {}) or {}

        url = req.get("url", "") or ""
        parsed = urlparse(url)
        method = (req.get("method", "GET") or "GET").upper()
        path = parsed.path or "/"

        req_headers = header_pairs(entry, "request")
        params, body_text, req_mime = post_pairs(entry)
        files = post_files(entry)

        http_request = HttpRequest(
            method=method,
            url=url,
            scheme=parsed.scheme or "https",
            host=parsed.hostname or "",
            port=str(parsed.port or ""),
            path=path,
            path_segments=[s for s in path.split("/") if s],
            query=[(k, v) for k, v in _query_pairs(parsed.query)],
            headers=req_headers,
            cookies=cookie_pairs(entry),
            body=_build_request_body(params, body_text, req_mime, files),
        )

        resp_headers = header_pairs(entry, "response")
        content = resp.get("content") or {}
        resp_mime = (content.get("mimeType") or "") or header_value(resp_headers, "content-type")
        resp_text = decode_response_text(content)
        status = resp.get("status", "")

        http_response = HttpResponse(
            status=status,
            headers=resp_headers,
            set_cookies=_parse_set_cookies(resp_headers),
            body=_build_text_body(resp_text, resp_mime),
            mime=resp_mime,
            redirect_location=header_value(resp_headers, "location"),
        )

        context = RequestContext(
            index=index,
            started=entry.get("startedDateTime", "") or "",
            time_ms=int(entry.get("time") or 0),
            pageref=entry.get("pageref") or "",
            referer=header_value(req_headers, "referer"),
            initiator=_initiator(entry),
        )

        requests.append(NormalizedRequest(request=http_request, response=http_response, context=context))

    return NormalizedCapture(
        requests=requests,
        pages=pages,
        total_har_entries=len(entries),
    )


def _query_pairs(query: str) -> list[tuple[str, str]]:
    from urllib.parse import parse_qsl
    return parse_qsl(query, keep_blank_values=True)
