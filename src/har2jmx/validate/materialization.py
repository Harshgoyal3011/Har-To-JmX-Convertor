"""Post-generation correlation materialization audit.

A correlation is successful ONLY when the FINAL JMX proves it. Discovery, classification and extractor
verification all operating correctly is not enough: if the downstream consumer still carries the literal,
the generated script does not exercise the dependency at all, while every intermediate report claims a
correlation. The JMX is the source of truth, so this audit re-reads the emitted plan and checks, per
correlation:

  1. the extractor exists in the plan, and
  2. it is attached to the PRODUCER's sampler, and
  3. at least one sampler references ``${variable}``, and
  4. no consumer request still carries the original value in any representation.

Anything else is ``MATERIALIZATION_FAILED`` and must not be counted as a correlation.

Deliberate non-failures:
  * COOKIE_MANAGER correlations are replayed by JMeter's Cookie Manager and intentionally have no
    variable;
  * a correlation whose extractor did not verify is deliberately dropped by the emitter (it ships the
    literal instead of a dead ``${var}``) — that is reported as SKIPPED_UNVERIFIED, not a failure,
    because the emitter chose it on purpose.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from urllib.parse import quote, quote_plus
from xml.dom import minidom

from har2jmx.correlate import ExtractorType


class MaterializationStatus(str, Enum):
    MATERIALIZED = "materialized"
    COOKIE_MANAGER = "cookie_manager"          # replayed by the Cookie Manager; no variable expected
    SKIPPED_UNVERIFIED = "skipped_unverified"  # emitter deliberately kept the literal
    SUPERSEDED = "superseded_by_longer_span"   # a longer substituted value already covers it
    FAILED = "materialization_failed"


@dataclass
class MaterializationCheck:
    variable: str
    value: str
    producer_index: int
    consumers: list[int] = field(default_factory=list)
    status: MaterializationStatus = MaterializationStatus.MATERIALIZED
    reason: str = ""
    location: str = ""

    @property
    def ok(self) -> bool:
        return self.status in (MaterializationStatus.MATERIALIZED,
                               MaterializationStatus.COOKIE_MANAGER,
                               MaterializationStatus.SUPERSEDED)

    def diagnostic(self) -> str:
        return (f"MATERIALIZATION_FAILED var=${{{self.variable}}} value={self.value!r} "
                f"producer=request#{self.producer_index} consumers={self.consumers} "
                f"location={self.location or 'n/a'} reason={self.reason}")


def covered_by_longer_span(result) -> set[str]:
    """Correlated values that a LONGER substitutable value already covers segment-for-segment.

    A multi-segment id ("sentence-transformers/all-MiniLM-L6-v2") and a sibling field equal to one of
    its segments ("sentence-transformers") are BOTH genuine producer->consumer dependencies, but in the
    consumer they occupy the SAME text. Substitution replaces the longest span, so the shorter value's
    variable would be referenced by nothing. Emitting its extractor anyway is a redundant extractor and
    a spurious MATERIALIZATION_FAILED, so the emitter suppresses it and this audit records it as
    SUPERSEDED rather than a failure. The longer span carries the value at run time.

    The longer value may be a correlation OR a parameter (a catalog id can legitimately own the span).
    Containment is segment-aligned - a contiguous run of whole "/" segments - matching how the span is
    discovered and substituted, so an unrelated value that merely shares text is never suppressed.
    """
    corr = [str(c.value) for c in result.correlations
            if c.extractor != ExtractorType.COOKIE_MANAGER]
    longer = list(corr)
    for d in getattr(result, "parameterization", None).datasets if getattr(result, "parameterization", None) else []:
        for row in d.rows:
            for v in row.values():
                if v not in (None, ""):
                    longer.append(str(v))
    covered: set[str] = set()
    for short in corr:
        s_parts = short.split("/")
        for long in longer:
            if long == short or len(long) <= len(short):
                continue
            l_parts = long.split("/")
            if any(l_parts[i:i + len(s_parts)] == s_parts
                   for i in range(len(l_parts) - len(s_parts) + 1)):
                covered.add(short)
                break
    return covered


def _elems(node):
    return [c for c in node.childNodes if c.nodeType == c.ELEMENT_NODE]


def _sampler_pairs(doc) -> list[tuple]:
    """(sampler element, its following hashTree) in document order."""
    out: list[tuple] = []

    def walk(container):
        kids = _elems(container)
        i = 0
        while i < len(kids):
            el = kids[i]
            ht = kids[i + 1] if i + 1 < len(kids) and kids[i + 1].tagName == "hashTree" else None
            if el.tagName == "HTTPSamplerProxy":
                out.append((el, ht))
            if ht is not None:
                walk(ht)
            elif el.tagName == "hashTree":
                walk(el)
            i += 2 if ht is not None else 1

    walk(doc.documentElement)
    return out


def _extractor_refnames(hashtree) -> set[str]:
    if hashtree is None:
        return set()
    names: set[str] = set()
    for tag, prop in (("JSONPostProcessor", "JSONPostProcessor.referenceNames"),
                      ("RegexExtractor", "RegexExtractor.refname")):
        for ex in hashtree.getElementsByTagName(tag):
            for sp in ex.getElementsByTagName("stringProp"):
                if sp.getAttribute("name") == prop and sp.firstChild:
                    names.add(sp.firstChild.nodeValue or "")
    return names


def _request_text(sampler, hashtree) -> str:
    """Only what the sampler SENDS (path, arguments, headers) — never its extractors, whose expressions
    may legitimately quote the recorded value."""
    parts = [sampler.toxml()]
    if hashtree is not None:
        for hm in hashtree.getElementsByTagName("HeaderManager"):
            parts.append(hm.toxml())
    return "\n".join(parts)


def _representations(value: str) -> list[str]:
    v = str(value)
    out = [v]
    for enc in (quote(v, safe=""), quote_plus(v), quote(v, safe="/")):
        if enc != v and enc not in out:
            out.append(enc)
    return out


def audit_materialization(result, xml: str | bytes) -> list[MaterializationCheck]:
    x = xml.decode("utf-8") if isinstance(xml, (bytes, bytearray)) else xml
    try:
        doc = minidom.parseString(x.encode("utf-8"))
    except Exception:  # noqa: BLE001
        return [MaterializationCheck(variable="*", value="*", producer_index=-1,
                                     status=MaterializationStatus.FAILED,
                                     reason="plan is not parseable XML")]

    pairs = _sampler_pairs(doc)
    included = [r.index for r in result.capture.requests if not r.classification.excluded]
    pos_of_index = {idx: pos for pos, idx in enumerate(included)}
    unresolved = {c.value for c in result.extractor_checks if not c.ok}
    superseded = covered_by_longer_span(result)

    checks: list[MaterializationCheck] = []
    for c in result.correlations:
        chk = MaterializationCheck(variable=c.variable, value=str(c.value),
                                   producer_index=c.producer_index, consumers=list(c.consumers))
        if c.extractor == ExtractorType.COOKIE_MANAGER:
            chk.status = MaterializationStatus.COOKIE_MANAGER
            checks.append(chk)
            continue
        if str(c.value) in superseded:
            chk.status = MaterializationStatus.SUPERSEDED
            chk.reason = "a longer substituted value covers this span; no separate extractor needed"
            checks.append(chk)
            continue
        if c.value in unresolved:
            chk.status = MaterializationStatus.SKIPPED_UNVERIFIED
            chk.reason = "extractor did not verify; emitter kept the literal by design"
            checks.append(chk)
            continue

        owners = [i for i, (s, ht) in enumerate(pairs) if c.variable in _extractor_refnames(ht)]
        if not owners:
            chk.status = MaterializationStatus.FAILED
            chk.reason = "no extractor for this variable exists in the plan"
            checks.append(chk)
            continue

        expected_pos = pos_of_index.get(c.producer_index)
        if expected_pos is not None and expected_pos not in owners:
            chk.status = MaterializationStatus.FAILED
            chk.location = f"sampler#{owners[0]}"
            chk.reason = (f"extractor is attached to sampler#{owners[0]} but the producer is "
                          f"request#{c.producer_index} (sampler#{expected_pos})")
            checks.append(chk)
            continue

        ref = "${%s}" % c.variable
        referencing = [i for i, (s, ht) in enumerate(pairs) if ref in _request_text(s, ht)]
        if not referencing:
            chk.status = MaterializationStatus.FAILED
            chk.reason = f"no sampler references {ref}; the consumer kept its literal"
            checks.append(chk)
            continue

        reps = _representations(c.value)
        leftover = []
        for i, (s, ht) in enumerate(pairs):
            if i in owners and i not in referencing:
                continue                       # the producer's own request may legitimately carry it
            text = _request_text(s, ht)
            if any(rep in text for rep in reps):
                leftover.append(i)
        if leftover:
            chk.status = MaterializationStatus.FAILED
            chk.location = f"sampler#{leftover[0]}"
            chk.reason = (f"sampler#{leftover[0]} still sends the original value "
                          f"(one of {reps!r}) instead of {ref}")
            checks.append(chk)
            continue

        chk.location = f"sampler#{referencing[0]}"
        checks.append(chk)
    return checks
