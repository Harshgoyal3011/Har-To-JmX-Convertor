"""Payload and HTTP role evidence for reconsidering a static-looking path."""

from __future__ import annotations

from urllib.parse import urljoin, urlsplit
from xml.etree import ElementTree as ET

from har2jmx.ir.normalized import BodyKind

_RENDER_DESTINATIONS = {"image", "style", "script", "font", "audio", "video", "track"}


def _scalar(value):
    return isinstance(value, (str, int, float)) and not isinstance(value, bool) and str(value).strip() != ""


def _has_record(value):
    if isinstance(value, dict):
        return sum(_scalar(v) for v in value.values()) >= 2 or any(
            _has_record(child) for child in value.values() if isinstance(child, (dict, list))
        )
    if isinstance(value, list):
        return any(_has_record(child) for child in value)
    return False


def _record_collection(value):
    """A collection of data records, rather than an arbitrary JSON container."""
    if isinstance(value, list):
        return any(isinstance(row, dict) and sum(_scalar(v) for v in row.values()) >= 2 for row in value)
    if isinstance(value, dict):
        return any(_record_collection(child) for child in value.values() if isinstance(child, (dict, list)))
    return False


def _scalar_values(value):
    if isinstance(value, dict):
        return {str(v) for child in value.values() for v in _scalar_values(child)}
    if isinstance(value, list):
        return {str(v) for child in value for v in _scalar_values(child)}
    return {str(value)} if _scalar(value) else set()


def _http_url(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = urlsplit(value)
        return parsed if parsed.scheme in {"http", "https"} and parsed.netloc else None
    except ValueError:
        return None


def _resource_catalog(value, request_url):
    """Self-describing resource plus a collection of links (including HATEOAS)."""
    if isinstance(value, dict):
        base = urlsplit(request_url)
        self_link = any((link.netloc, link.path, link.query) == (base.netloc, base.path, base.query)
                        for v in value.values() if (link := _http_url(v)) is not None)
        link_collection = any(
            isinstance(v, list) and v and all(
                isinstance(item, dict) and any(
                    _http_url(link) is not None
                    for link in item.values()
                ) for item in v
            ) for v in value.values()
        )
        if self_link and link_collection:
            return True
        # Standard hypermedia controls express resource navigation, not rendering.
        links = value.get("_links")
        if isinstance(links, dict) and isinstance(links.get("self"), dict):
            href = links["self"].get("href")
            try:
                matches_self = isinstance(href, str) and urljoin(request_url, href) == request_url
            except ValueError:
                matches_self = False
            if matches_self and len(links) > 1:
                return True
        return any(_resource_catalog(v, request_url) for v in value.values() if isinstance(v, (dict, list)))
    if isinstance(value, list):
        return any(_resource_catalog(v, request_url) for v in value)
    return False


def business_content_evidence(req, *, api_path: bool = False) -> str:
    """JSON/XML alone is insufficient; require data structure plus HTTP role evidence.

    Known telemetry/third-party decisions run before this check. Rendering MIME,
    fetch destinations, and empty/invalid bodies cannot be rescued by JSON shape.
    """
    headers = {name.lower(): value.lower() for name, value in req.request.headers}
    if headers.get("sec-fetch-dest") in _RENDER_DESTINATIONS or headers.get("sec-fetch-mode") == "no-cors":
        return ""
    body = req.response.body
    if body.kind in {BodyKind.JSON, BodyKind.GRAPHQL} and isinstance(body.json, (dict, list)):
        if _resource_catalog(body.json, req.request.url):
            return "self-described resource/link catalog in an application response"
        if _record_collection(body.json):
            return "structured collection of data records, without a browser rendering role"
        # A cache-busting query is not data intent. An actual request selector
        # reused in the record is role evidence regardless of field vocabulary.
        path_selection = bool(set(req.request.path_segments) & _scalar_values(body.json))
        query_selection = isinstance(body.json, dict) and any(
            name in body.json and _scalar(body.json[name]) and str(body.json[name]) == str(value)
            for name, value in req.request.query
        )
        data_request = api_path or req.request.body.is_structured or path_selection or query_selection
        if data_request and _has_record(body.json):
            return "record response to an API/structured-input/data-query request"
    if body.kind in {BodyKind.XML, BodyKind.SOAP} and body.raw:
        try:
            root = ET.fromstring(body.raw)
        except ET.ParseError:
            return ""
        # XML typing also includes HTML/SVG: document markup is not API evidence.
        if root.tag.rsplit("}", 1)[-1].lower() in {"html", "svg"}:
            return ""
        records = any(sum(bool(child.text and child.text.strip()) for child in node) >= 2 for node in root.iter())
        if records and (api_path or req.request.body.is_structured or bool(req.request.query)):
            return "XML records in an API/structured-input/data-query response"
    return ""
