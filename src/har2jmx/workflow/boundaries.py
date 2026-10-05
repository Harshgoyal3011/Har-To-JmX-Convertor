"""Evidence-backed interaction boundaries, independent of display names.

Timing alone is never a proven boundary here. Under-specified captures retain
their legacy partition with explicit uncertainty. Redirect execution ownership
is preserved by refusing to split any observed redirect interval.
"""
from __future__ import annotations

import json
import re
from urllib.parse import urldefrag, urljoin

_EVENT = re.compile(
    r"(?:^|[_.$])(?:click|dblclick|submit|change|input|keydown|keyup|pointerdown|pointerup)(?:[_.$]|$)",
    re.IGNORECASE,
)


def event_sites(request):
    """Source call sites are context, never unique instances of an event."""
    stack = request.context.initiator_detail.get("stack") or {}
    sites = []
    while isinstance(stack, dict) and stack:
        for frame in stack.get("callFrames", []) or []:
            name = frame.get("functionName") or ""
            if _EVENT.search(name):
                sites.append((name, urldefrag(frame.get("url") or "")[0],
                              frame.get("lineNumber"), frame.get("columnNumber")))
        stack = stack.get("parent") or {}
    return sites


def redirect_intervals(capture):
    intervals = []
    for source in capture.requests:
        if str(source.status) not in {"301", "302", "303", "307", "308"}:
            continue
        if not source.response.redirect_location:
            continue
        target = urldefrag(urljoin(source.request.url, source.response.redirect_location))[0]
        for request in capture.requests[source.index + 1:]:
            if urldefrag(request.request.url)[0] == target:
                intervals.append((source.index, request.index))
                break
    return intervals


def boundary_evidence(capture):
    intervals = redirect_intervals(capture)
    last_site = None
    evidence = {}
    for request in capture.requests:
        headers = {key.lower(): value for key, value in request.request.headers}
        sites = event_sites(request)
        site = json.dumps(sites[-1]) if sites else ""
        continuation = any(start < request.index <= end for start, end in intervals)
        eligible = not request.classification.excluded and request.classification.role.value != "auth"
        document = (headers.get("sec-fetch-dest") == "document"
                    and headers.get("sec-fetch-mode") == "navigate"
                    and headers.get("sec-fetch-user") == "?1")
        changed_site = bool(site and last_site and site != last_site)
        if request.index and eligible and not continuation:
            if document:
                evidence[request.index] = "user_activated_top_level_document_navigation"
            elif changed_site:
                evidence[request.index] = "changed_explicit_event_listener_call_site"
        if site and not request.classification.excluded:
            last_site = site
    return evidence


def refine_boundaries(capture, transactions, anchor_priority, anchor_name):
    """Split only supported boundaries and retain every index in captured order."""
    from har2jmx.workflow.transactions import Transaction

    evidence = boundary_evidence(capture)
    refined = []
    for transaction in transactions:
        groups = []
        current = []
        for index in transaction.request_indices:
            if index in evidence and current and any(
                not capture.requests[i].classification.excluded for i in current
            ):
                groups.append(current)
                current = []
            current.append(index)
        if current:
            groups.append(current)
        for position, indices in enumerate(groups):
            business = [i for i in indices if not capture.requests[i].classification.excluded]
            anchor = max((capture.requests[i] for i in business or indices), key=anchor_priority)
            name, category = anchor_name(anchor)
            if position == 0 and transaction.name == "Launch Application":
                name, category = transaction.name, transaction.category
            first = next((i for i in indices if i in evidence), indices[0])
            reason = evidence.get(first)
            refined.append(Transaction(
                name=name, category=category, anchor_index=anchor.index,
                request_indices=indices, business_indices=business,
                boundary_confidence="supported" if reason else "capture_start" if indices[0] == 0 else "uncertain",
                boundary_reasons=[reason or ("capture_start" if indices[0] == 0 else "legacy_partition_ui_evidence_insufficient")],
            ))
    return refined
