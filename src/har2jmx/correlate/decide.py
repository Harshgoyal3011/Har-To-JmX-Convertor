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


_LIST_IDX_RE = re.compile(r"\[\d+\]")


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
    if location.startswith("response.body:"):
        return ExtractorType.JSON, _json_path(location)
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
    seen: set[tuple[str, str]] = set()

    verdicts: list[ValueVerdict] = [
        v for v in classification.verdicts
        if v.classification == ValueClass.RUNTIME_GENERATED and v.consumers
    ]
    for v in verdicts:
        flow = lineage.by_value(v.value)
        if flow is None or flow.first_producer is None:
            continue
        producer = flow.first_producer
        var = variable_name(v.entity_field or producer.field or "value")
        key = (var, v.value)
        if key in seen:
            continue
        seen.add(key)

        extractor, expr = _choose_extractor(producer.location, producer.field, flow.consumers)
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
        ))

    decisions.sort(key=lambda d: (d.producer_index, d.variable))
    return decisions
