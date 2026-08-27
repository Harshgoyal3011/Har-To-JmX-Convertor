from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from har2jmx.har.reader import header_pairs, header_value
from har2jmx.patterns import (
    API_PATH_RE,
    NOISE_HOST_RE,
    NOISE_PATH_RE,
    STATIC_EXTENSIONS,
    STATIC_PATH_RE,
    STATIC_RESOURCE_TYPES,
)


def is_application_request(entry: dict[str, Any]) -> bool:
    request = entry.get("request", {})
    method = request.get("method", "GET").upper()
    parsed = urlparse(request.get("url", ""))
    path = parsed.path or "/"
    suffix = Path(path.lower()).suffix
    request_headers = header_pairs(entry)
    accept = header_value(request_headers, "Accept").lower()
    content_type = header_value(request_headers, "Content-Type").lower()
    response_mime = ((entry.get("response", {}).get("content") or {}).get("mimeType") or "").lower()
    resource_type = (entry.get("_resourceType") or entry.get("resourceType") or "").lower()

    if NOISE_HOST_RE.search(parsed.netloc) or NOISE_PATH_RE.search(path):
        return False
    if resource_type in {"xhr", "fetch", "document"}:
        return True
    if method not in {"GET", "HEAD"}:
        return True
    if API_PATH_RE.search(path):
        return True
    if "json" in content_type or "graphql" in content_type or "xml" in content_type:
        return True
    if "json" in response_mime or "xml" in response_mime:
        return True
    if "text/html" in response_mime and not STATIC_PATH_RE.search(path):
        return True
    if suffix in STATIC_EXTENSIONS or STATIC_PATH_RE.search(path):
        return False
    if resource_type in STATIC_RESOURCE_TYPES:
        return False
    if any(kind in response_mime for kind in ["css", "javascript", "image/", "font", "audio/", "video/"]):
        return False
    if accept and not any(kind in accept for kind in ["html", "json", "xml", "*/*"]):
        return False
    return True
