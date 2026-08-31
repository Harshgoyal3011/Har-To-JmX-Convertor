"""Milestone 9 — lifecycle-aware correlation engine.

Turns the RUNTIME_GENERATED verdicts from M8 into correlation decisions with a structured-first
extractor strategy (JSON > header regex > Set-Cookie), never from ID-shape or repetition. A value is
correlated only when it was server-issued/created this run AND proven consumed by a later request.
Rules honored: no extractor without a downstream consumer; no duplicate extractors; cookies replayed
by the Cookie Manager get no redundant extractor.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum

from har2jmx.classify import ClassificationResult, ValueClass, classify_values
from har2jmx.classify.value_engine import ValueVerdict
from har2jmx.ir.normalized import NormalizedCapture
from har2jmx.lineage import LineageGraph, Occurrence, build_lineage
from har2jmx.utils import variable_name


class ExtractorType(str, Enum):
    JSON = "json"
    REGEX = "regex"
    CSS = "css"
    BOUNDARY = "boundary"
    COOKIE_MANAGER = "cookie_manager"   # no explicit extractor — JMeter Cookie Manager replays it


@dataclass
class CorrelationDecision:
    variable: str
    value: str
    producer_index: int
    producer_location: str
    extractor: ExtractorType
    expression: str
    consumers: list[int] = field(default_factory=list)
    confidence: str = "Medium"
    reason: str = ""
    entity: str | None = None
    from_redirect: bool = False


_LIST_IDX_RE = re.compile(r"\[\d+\]")
_GENERIC_ID_NAMES = {"id", "code", "key", "number", "uuid", "guid", "ref", "reference", "identifier", "no"}


def _camel(entity: str, field: str) -> str:
    e = re.sub(r"[^A-Za-z0-9]", "", entity)
    if not e:
        return field
    return e[0].lower() + e[1:] + field[0].upper() + field[1:]


def _json_path(producer_location: str) -> str:
    keypath = producer_location.split("response.body:", 1)[1]
    keypath = _LIST_IDX_RE.sub("", keypath)
    return f"$.{keypath}" if "." in keypath else f"$..{keypath}"


def _all_consumers_are_cookies(consumers: list[Occurrence]) -> bool:
    return bool(consumers) and all(o.location.startswith("request.cookie:") for o in consumers)


def _choose_extractor(location: str, cookie_name: str, consumers: list[Occurrence]) -> tuple[ExtractorType, str]:
    if location.startswith("set-cookie:"):
        if _all_consumers_are_cookies(consumers):
            return ExtractorType.COOKIE_MANAGER, ""
        return ExtractorType.REGEX, rf"Set-Cookie:\s*{re.escape(cookie_name)}=([^;]+)"
    if location.startswith("response.regex:"):        # embedded / boundary match (prebuilt regex)
        return ExtractorType.REGEX, location.split("response.regex:", 1)[1]
    if location.startswith("response.body:"):
        return ExtractorType.JSON, _json_path(location)
    if location.startswith("response.location:"):
        param = location.split("response.location:", 1)[1]
        return ExtractorType.REGEX, rf"[?&]{re.escape(param)}=([^&\s\"']+)"
    if location.startswith("response.header:"):
        header = location.split("response.header:", 1)[1]
        return ExtractorType.REGEX, rf"{re.escape(header)}:\s*(.+)"
    if location.startswith("response.html:"):
        field = location.split("response.html:", 1)[1]
        return ExtractorType.REGEX, rf'name=["\']{re.escape(field)}["\'][^>]*value=["\']([^"\']*)["\']'
    if location.startswith("response.xml:"):
        tag = location.split("response.xml:", 1)[1]
        return ExtractorType.REGEX, rf"<(?:[\w.-]+:)?{re.escape(tag)}(?:\s[^>]*)?>([^<]+)</"
    return ExtractorType.REGEX, ""


def build_correlations(cap: NormalizedCapture,
                       classification: ClassificationResult | None = None,
                       lineage: LineageGraph | None = None) -> list[CorrelationDecision]:
    lineage = lineage if lineage is not None else build_lineage(cap)
    classification = classification if classification is not None else classify_values(cap, lineage)

    decisions: list[CorrelationDecision] = []
    assigned: dict[str, str] = {}   # variable name -> value, to guarantee unique names

    verdicts: list[ValueVerdict] = [
        v for v in classification.verdicts
        if v.classification == ValueClass.RUNTIME_GENERATED and v.consumers
    ]

    # Assign variable names in document order (earliest producer first) so that when one field is
    # issued more than once — e.g. an access_token re-issued by a token refresh — the FIRST value
    # keeps the clean base name (access_token) and later re-issues are suffixed (access_token2),
    # which reads the way an engineer would name them rather than by whichever had more consumers.
    def _producer_index(v: ValueVerdict) -> int:
        f = lineage.by_value(v.value)
        return f.first_producer.request_index if f and f.first_producer else 1_000_000

    verdicts.sort(key=lambda v: (_producer_index(v), str(v.value)))

    for v in verdicts:
        flow = lineage.by_value(v.value)
        if flow is None or flow.first_producer is None:
            continue
        producer = flow.first_producer
        base = variable_name(v.entity_field or producer.field or "value")
        # a generic id ("id"/"code"/"key"...) with a known entity is qualified (orderId, shipmentId)
        # so two different entities' ids never share one JMeter variable and clobber each other.
        if v.entity and base.lower() in _GENERIC_ID_NAMES:
            base = variable_name(_camel(v.entity, base))
        var = base
        n = 2
        while var in assigned and assigned[var] != v.value:   # different value → new unique name
            var, n = f"{base}{n}", n + 1
        if assigned.get(var) == v.value:                       # exact correlation already recorded
            continue
        assigned[var] = v.value

        extractor, expr = _choose_extractor(producer.location, producer.field, flow.consumers)
        # a value read from a redirect Location can only be extracted if the producer does NOT follow
        # the redirect — flag it so the emitter disables auto-redirect on that sampler.
        from_redirect = producer.location.startswith(("response.location:", "response.header:Location"))
        decisions.append(CorrelationDecision(
            variable=var,
            value=v.value,
            producer_index=producer.request_index,
            producer_location=producer.location,
            extractor=extractor,
            expression=expr,
            consumers=v.consumers,
            confidence=v.confidence,
            reason=v.reason,
            entity=v.entity,
            from_redirect=from_redirect,
        ))

    decisions.sort(key=lambda d: (d.producer_index, d.variable))
    return decisions
