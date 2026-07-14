"""Intermediate Representation — future single source of truth for the compiler.

Phase 1 (this module): IR types exist and HAR parsing constructs RequestIR first.
Downstream engines still consume SamplerModel via compat adapters so behavior
is unchanged. Later phases will migrate engines onto ScriptIR / DependencyGraph
one module at a time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RequestIR:
    """One application HTTP exchange, detached from the raw HAR entry.

    Mirrors the fields currently used by SamplerModel so conversion is lossless.
    Downstream modules must not need the original HAR dict once this exists.
    """

    name: str
    method: str
    url: str
    protocol: str
    domain: str
    port: str
    path: str
    query: list[tuple[str, str]]
    headers: list[tuple[str, str]]
    cookies: list[tuple[str, str]]
    response_headers: list[tuple[str, str]]
    post_params: list[tuple[str, str]]
    post_body: str
    mime_type: str
    transaction: str
    status: int | str
    time_ms: int
    response_text: str = ""
    # Populated later by correlation; kept here so IR can own the attachment point
    correlation_ids: list[str] = field(default_factory=list)
    # Stable index within ScriptIR.requests (set by analyzer later)
    index: int = -1
    # Original HAR page reference when available
    pageref: str = ""


@dataclass
class ScriptIR:
    """Compiled view of a HAR capture — the script under construction.

    Today this only carries requests + capture metadata. Correlations,
    parameters, entities, and the dependency graph will attach here in
    later incremental steps — not in this refactor.
    """

    requests: list[RequestIR]
    total_har_entries: int
    pages: dict[str, str] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def request_count(self) -> int:
        return len(self.requests)
