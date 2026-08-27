"""Normalized Intermediate Representation (IR) — the spine of the redesigned pipeline.

Milestone 1. Every downstream reasoning stage (noise classification, workflow, entity
discovery, value lineage, classification, correlation, parameterization, emit) consumes this
IR and *annotates* it. No stage re-parses the HAR.

This IR is framework-independent: it describes HTTP exchanges and their capture context, plus
placeholders the later stages fill in (classification, lineage). It is intentionally separate
from the legacy ``ir.models.RequestIR`` used by the current live pipeline, which stays in place
until the staged pipeline reaches parity (strangler migration).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class BodyKind(str, Enum):
    NONE = "none"
    JSON = "json"
    FORM = "form"                 # application/x-www-form-urlencoded
    MULTIPART = "multipart"       # multipart/form-data
    GRAPHQL = "graphql"           # JSON body carrying a GraphQL operation
    SOAP = "soap"                 # SOAP envelope
    XML = "xml"                   # non-SOAP XML
    TEXT = "text"
    BINARY = "binary"


class RequestRole(str, Enum):
    """Filled by Milestone 2 (request noise classification). Default UNKNOWN here."""
    UNKNOWN = "unknown"
    STATIC = "static"
    TELEMETRY = "telemetry"
    AUTH = "auth"
    BUSINESS = "business"
    POLLING = "polling"
    UPLOAD = "upload"
    DOWNLOAD = "download"


@dataclass
class Body:
    kind: BodyKind = BodyKind.NONE
    mime: str = ""
    raw: str = ""
    form: list[tuple[str, str]] = field(default_factory=list)  # form / multipart fields
    json: Any = None                                           # parsed JSON (json/graphql bodies)
    graphql_operation: str = ""                                # operationName when kind == GRAPHQL

    @property
    def is_structured(self) -> bool:
        return self.kind in {BodyKind.JSON, BodyKind.GRAPHQL, BodyKind.XML, BodyKind.SOAP, BodyKind.FORM}


@dataclass
class HttpRequest:
    method: str
    url: str
    scheme: str
    host: str
    port: str
    path: str
    path_segments: list[str]
    query: list[tuple[str, str]]
    headers: list[tuple[str, str]]
    cookies: list[tuple[str, str]]
    body: Body


@dataclass
class HttpResponse:
    status: int | str
    headers: list[tuple[str, str]]
    set_cookies: list[tuple[str, str]]   # parsed from Set-Cookie response headers
    body: Body
    mime: str = ""
    redirect_location: str = ""          # Location header on 3xx


@dataclass
class RequestContext:
    index: int                           # 0-based sequence within the capture
    started: str = ""                    # ISO-8601 timestamp (startedDateTime)
    time_ms: int = 0
    pageref: str = ""
    referer: str = ""
    initiator: str = ""                  # best-effort from HAR _initiator
    transaction: str = ""                # user-action name (Milestone 4)


@dataclass
class RequestClassification:
    """Owned here (Milestone 1), populated by Milestone 2. Kept auditable via ``reasons``."""
    role: RequestRole = RequestRole.UNKNOWN
    reasons: list[str] = field(default_factory=list)
    static_candidate: bool = False
    telemetry_candidate: bool = False
    auth_candidate: bool = False
    business_candidate: bool = False
    polling_candidate: bool = False
    upload_candidate: bool = False
    download_candidate: bool = False
    # Decision (Milestone 2): should this request be excluded from business replay/scripting?
    # A request is only excluded when it does not contribute to business replay. Never deleted —
    # excluded requests remain in the capture and are listed in the classification report.
    excluded: bool = False
    exclusion_reason: str = ""


@dataclass
class NormalizedRequest:
    request: HttpRequest
    response: HttpResponse
    context: RequestContext
    classification: RequestClassification = field(default_factory=RequestClassification)

    # ---- convenience accessors used throughout the pipeline ----
    @property
    def method(self) -> str:
        return self.request.method

    @property
    def path(self) -> str:
        return self.request.path

    @property
    def host(self) -> str:
        return self.request.host

    @property
    def status(self) -> int | str:
        return self.response.status

    @property
    def index(self) -> int:
        return self.context.index

    def label(self) -> str:
        p = self.request.path
        p = p[:60] + ("…" if len(p) > 60 else "")
        return f"{self.request.method} {p} {self.response.status}".strip()


@dataclass
class NormalizedCapture:
    """The full normalized capture — every HAR entry, nothing dropped.

    Noise/static requests are *tagged* (Milestone 2), never removed here, so every downstream
    decision stays auditable against the complete capture.
    """
    requests: list[NormalizedRequest]
    pages: dict[str, str] = field(default_factory=dict)
    total_har_entries: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def count(self) -> int:
        return len(self.requests)
