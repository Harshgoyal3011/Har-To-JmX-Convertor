"""Static "dry-run" validator for a generated JMeter plan.

Scans the emitted JMX for the defects that would make a script fail or mislead in production, without
running JMeter: malformed XML, missing constituents, unresolved ${variables}, leaked secret values,
and extractors that feed nothing. Use it as an acceptance gate on generated scripts.
"""

from __future__ import annotations

import re
from xml.dom import minidom

from har2jmx.engine import EngineResult

_CONSTITUENTS = [
    "ThreadGroup", "HTTP Request Defaults", "HTTP Cookie Manager", "HTTP Header Manager",
    "ResponseAssertion", "UniformRandomTimer", "TransactionController", "HTTPSamplerProxy",
]
_UDV = {"THREADS", "LOOPS", "RAMP"}
_VAR_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def validate_plan(result: EngineResult, xml: str | bytes) -> list[str]:
    """Return a list of human-readable issues; empty means the plan is production-clean."""
    x = xml.decode("utf-8") if isinstance(xml, (bytes, bytearray)) else xml
    issues: list[str] = []

    try:
        minidom.parseString(x.encode("utf-8"))
    except Exception as e:  # noqa: BLE001
        issues.append(f"malformed XML: {e}")
        return issues  # nothing else is meaningful if the XML is broken

    missing = [c for c in _CONSTITUENTS if c not in x]
    if missing:
        issues.append("missing constituents: " + ", ".join(missing))

    refs = set(_VAR_RE.findall(x))
    extractors = set(re.findall(r'referenceNames">([^<]+)<', x)) | set(re.findall(r'RegexExtractor\.refname">([^<]+)<', x))
    csv_cols: set[str] = set()
    for names in re.findall(r'variableNames">([^<]+)<', x):
        csv_cols |= {c.strip() for c in names.split(",") if c.strip()}

    unresolved = refs - extractors - csv_cols - _UDV
    if unresolved:
        issues.append("unresolved variables (no extractor/CSV/UDV source): " + ", ".join(sorted(unresolved)))

    # only the request-carrying props matter for a "hardcoded secret" — not timer/assertion config
    request_content = "\n".join(
        re.findall(r'(?:Argument\.value|HTTPSampler\.path|Header\.value)">([^<]*)<', x)
    )
    leaked = sorted({c.variable for c in result.correlations if c.value and c.value in request_content})
    if leaked:
        issues.append("correlation value shipped literally in a request (should be a variable): " + ", ".join(leaked))

    unused = sorted(e for e in extractors if e not in refs)
    if unused:
        issues.append("extractor with no downstream consumer: " + ", ".join(unused))

    empty = [d.name for d in result.parameterization.datasets if d.row_count == 0]
    if empty:
        issues.append("empty dataset: " + ", ".join(empty))

    return issues
