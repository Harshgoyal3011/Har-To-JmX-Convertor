from __future__ import annotations

import base64
import json
from typing import Any
from urllib.parse import parse_qsl


def read_har(upload: bytes) -> dict[str, Any]:
    try:
        data = json.loads(upload.decode("utf-8-sig"))
    except UnicodeDecodeError:
        data = json.loads(upload.decode("latin-1"))
    if "log" not in data or "entries" not in data["log"]:
        raise ValueError("The uploaded file is not a valid HAR export.")
    return data


def header_pairs(entry: dict[str, Any], direction: str = "request") -> list[tuple[str, str]]:
    headers = entry.get(direction, {}).get("headers", []) or []
    return [(h.get("name", ""), h.get("value", "")) for h in headers if h.get("name")]


def cookie_pairs(entry: dict[str, Any]) -> list[tuple[str, str]]:
    cookies = entry.get("request", {}).get("cookies", []) or []
    return [(c.get("name", ""), c.get("value", "")) for c in cookies if c.get("name")]


def header_value(headers: list[tuple[str, str]], name: str) -> str:
    for header_name, value in headers:
        if header_name.lower() == name.lower():
            return value or ""
    return ""


def post_pairs(entry: dict[str, Any]) -> tuple[list[tuple[str, str]], str, str]:
    post = entry.get("request", {}).get("postData") or {}
    mime_type = post.get("mimeType", "")
    params = [(p.get("name", ""), p.get("value", "")) for p in post.get("params", []) if p.get("name")]
    text = post.get("text") or ""
    if not params and text and "application/x-www-form-urlencoded" in mime_type:
        params = parse_qsl(text, keep_blank_values=True)
    return params, text, mime_type


def decode_response_text(content: dict[str, Any]) -> str:
    text = content.get("text") or ""
    if not isinstance(text, str):
        return ""
    if content.get("encoding") == "base64":
        try:
            return base64.b64decode(text.encode("utf-8"), validate=True).decode("utf-8", errors="replace")
        except Exception:
            return ""
    return text
