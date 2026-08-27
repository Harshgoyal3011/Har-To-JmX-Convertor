from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qsl, urlparse

from har2jmx.har.filter import is_application_request
from har2jmx.har.reader import cookie_pairs, decode_response_text, header_pairs, post_pairs
from har2jmx.ir.compat import script_ir_to_samplers
from har2jmx.ir.models import RequestIR, ScriptIR
from har2jmx.models import SamplerModel
from har2jmx.patterns import (
    BUSINESS_TRANSACTION_RULES,
    _ACTION_METHODS,
    _ACTION_PATH_RE,
    _SPA_GAP_MS,
)


def _label_from_path(method: str, path: str) -> str:
    if method in _ACTION_METHODS and re.search(r"/(login|auth|signin|token|sso|oauth)", path, re.IGNORECASE):
        return "Login"
    for pattern, label in BUSINESS_TRANSACTION_RULES:
        if pattern.search(path):
            return label
    segments = [
        s for s in path.split("/")
        if s
        and not re.match(r"^[0-9a-f\-]{8,}$", s, re.IGNORECASE)
        and not s.isdigit()
        and not re.match(r"^v\d+$", s, re.IGNORECASE)
    ]
    if segments:
        return segments[-1].replace("-", " ").replace("_", " ").title()
    return "Application Flow"


def _clean_page_title(title: str | None) -> str | None:
    if not title:
        return None
    t = title.strip()
    if len(t) < 3 or len(t) > 80:
        return None
    if t.startswith(("http", "/", "chrome", "about:")):
        return None
    if re.match(r"^page[\s_-]?\d+$", t, re.IGNORECASE):
        return None
    if re.match(r"^[/\w\-]+/[/\w\-]+$", t):
        return None
    return t


def _detect_action_boundary(prev_entry: dict, curr_entry: dict, same_page: bool) -> bool:
    if not same_page:
        return True

    prev_started = prev_entry.get("startedDateTime", "")
    curr_started = curr_entry.get("startedDateTime", "")
    if prev_started and curr_started:
        try:
            from datetime import datetime as _dt

            def _parse_iso(s: str) -> _dt:
                s = s.strip()
                s = re.sub(r"Z$", "", s)
                s = re.sub(r"\+\d{2}:\d{2}$", "", s)
                s = s[:26]
                return _dt.fromisoformat(s)

            t0 = _parse_iso(prev_started)
            t1 = _parse_iso(curr_started)
            gap_ms = (t1 - t0).total_seconds() * 1000
            if gap_ms > _SPA_GAP_MS:
                return True
        except Exception:
            pass

    return False


def assign_transaction_groups(har_entries: list[dict], pages: dict[str, str]) -> list[str]:
    if not har_entries:
        return []

    n = len(har_entries)
    assignments: list[str] = [""] * n

    i = 0
    group_start = 0
    current_pageref = har_entries[0].get("pageref") or "__nopage__"

    def _name_group(start: int, end: int, label: str) -> None:
        for k in range(start, end):
            assignments[k] = label

    while i <= n:
        end_of_group = (i == n) or (har_entries[i].get("pageref") or "__nopage__") != current_pageref

        if end_of_group:
            group_entries = har_entries[group_start:i]
            page_title = _clean_page_title(pages.get(current_pageref))

            if page_title:
                _name_group(group_start, i, page_title)
            else:
                sub_start = group_start
                sub_label: str | None = None

                for j in range(group_start, i):
                    entry = har_entries[j]
                    req = entry.get("request", {})
                    method = req.get("method", "GET").upper()
                    url = req.get("url", "")
                    path = urlparse(url).path

                    is_action = method in _ACTION_METHODS or _ACTION_PATH_RE.search(path)

                    if j > sub_start:
                        boundary = _detect_action_boundary(
                            har_entries[j - 1], entry,
                            same_page=(entry.get("pageref") or "__nopage__") == (har_entries[j - 1].get("pageref") or "__nopage__"),
                        )
                        if boundary:
                            if sub_label is None:
                                sub_label = _label_from_path(
                                    har_entries[sub_start].get("request", {}).get("method", "GET"),
                                    urlparse(har_entries[sub_start].get("request", {}).get("url", "")).path,
                                )
                            _name_group(sub_start, j, sub_label)
                            sub_start = j
                            sub_label = None

                    if sub_label is None and is_action:
                        sub_label = _label_from_path(method, path)

                if sub_label is None and sub_start < i:
                    first = har_entries[sub_start]
                    sub_label = _label_from_path(
                        first.get("request", {}).get("method", "GET"),
                        urlparse(first.get("request", {}).get("url", "")).path,
                    )
                if sub_start < i:
                    _name_group(sub_start, i, sub_label or "Application Flow")

            if i < n:
                current_pageref = har_entries[i].get("pageref") or "__nopage__"
                group_start = i

        i += 1

    return assignments


def build_script_ir(har: dict[str, Any]) -> ScriptIR:
    """Parse + filter + group a HAR into Intermediate Representation.

    This is the only HAR→domain translation step. Downstream engines should
    eventually consume ScriptIR directly; today build_samplers() adapts IR
    back to SamplerModel so existing correlation/parameterization/JMX code
    keeps working unchanged.
    """
    pages: dict[str, str] = {
        page.get("id", ""): page.get("title") or page.get("id") or ""
        for page in har.get("log", {}).get("pages", [])
    }
    all_entries: list[dict] = har.get("log", {}).get("entries", [])
    total_har_entries = len(all_entries)

    app_entries: list[tuple[int, dict]] = [
        (i, e) for i, e in enumerate(all_entries) if is_application_request(e)
    ]

    if not app_entries:
        return ScriptIR(requests=[], total_har_entries=total_har_entries, pages=pages)

    filtered_entries = [e for _, e in app_entries]
    transaction_names = assign_transaction_groups(filtered_entries, pages)

    requests: list[RequestIR] = []
    for seq_idx, (_orig_idx, entry) in enumerate(app_entries):
        request = entry.get("request", {})
        url = request.get("url", "")
        parsed = urlparse(url)
        method = request.get("method", "GET").upper()
        path = parsed.path or "/"
        query = parse_qsl(parsed.query, keep_blank_values=True)
        post_params, post_body, mime_type = post_pairs(entry)
        response_content = entry.get("response", {}).get("content") or {}
        response_text = decode_response_text(response_content)
        status = entry.get("response", {}).get("status", "")
        time_ms = int(entry.get("time") or 0)

        path_label = path[:60] + ("..." if len(path) > 60 else "")
        name = f"{method} {path_label} {status}".strip()
        transaction = transaction_names[seq_idx] if seq_idx < len(transaction_names) else "Application Flow"
        pageref = entry.get("pageref") or ""

        requests.append(RequestIR(
            name=name,
            method=method,
            url=url,
            protocol=parsed.scheme or "https",
            domain=parsed.hostname or "",
            port=str(parsed.port or ""),
            path=path,
            query=query,
            headers=header_pairs(entry),
            cookies=cookie_pairs(entry),
            response_headers=header_pairs(entry, "response"),
            post_params=post_params,
            post_body=post_body,
            mime_type=mime_type,
            transaction=transaction,
            status=status,
            time_ms=time_ms,
            response_text=response_text,
            index=seq_idx,
            pageref=pageref,
        ))

    return ScriptIR(
        requests=requests,
        total_har_entries=total_har_entries,
        pages=pages,
    )


def build_samplers(har: dict[str, Any]) -> list[SamplerModel]:
    """Backward-compatible facade: HAR → ScriptIR → list[SamplerModel]."""
    return script_ir_to_samplers(build_script_ir(har))
