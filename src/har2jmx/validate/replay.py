"""Milestone 11 — replay validator (static multi-iteration analysis).

Checks the correlation (M9) and parameterization (M10) decisions against the classification (M8) and
lineage (M7) for the defect classes that break replay: variables used before extraction, runtime
values mistakenly placed in a CSV, business master data mistakenly correlated, missing correlations,
session repeatability, and per-iteration data variation. Genuine ambiguities are flagged for review;
nothing is guessed.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from har2jmx.classify import ClassificationResult, ValueClass, classify_values
from har2jmx.correlate import CorrelationDecision, ExtractorType
from har2jmx.ir.normalized import NormalizedCapture
from har2jmx.lineage import LineageGraph, build_lineage
from har2jmx.parameterize import ParameterizationPlan
from har2jmx.understand import detect_auth

_WEIGHT = {"CRITICAL": 40, "HIGH": 20, "MEDIUM": 10, "LOW": 3, "INFO": 0}


@dataclass
class Finding:
    check: str
    passed: bool
    severity: str            # CRITICAL | HIGH | MEDIUM | LOW | INFO
    detail: str
    auto_repaired: bool = False


@dataclass
class ReplayReport:
    findings: list[Finding] = field(default_factory=list)
    score: int = 100
    passed: bool = False

    def issues(self) -> list[Finding]:
        return [f for f in self.findings if not f.passed]


def validate_replay(cap: NormalizedCapture,
                    correlations: list[CorrelationDecision],
                    plan: ParameterizationPlan,
                    classification: ClassificationResult | None = None,
                    lineage: LineageGraph | None = None) -> ReplayReport:
    lineage = lineage if lineage is not None else build_lineage(cap)
    classification = classification if classification is not None else classify_values(cap, lineage)
    value_class = {v.value: v.classification for v in classification.verdicts}
    corr_values = {c.value for c in correlations}

    findings: list[Finding] = []

    def add(check: str, passed: bool, severity: str, detail: str) -> None:
        findings.append(Finding(check, passed, severity, detail))

    # 1. No variable is consumed before it is extracted
    early = [
        c.variable for c in correlations
        if any(idx <= c.producer_index for idx in c.consumers)
    ]
    add("No variable consumed before extraction", not early, "HIGH",
        "All extractors run before their consumers." if not early
        else f"Consumed-before-extracted: {', '.join(early[:5])}")

    # 2. No runtime-generated value sits in a CSV/dataset
    runtime_in_csv = sorted({
        v for d in plan.datasets for row in d.rows for v in row.values()
        if value_class.get(v) == ValueClass.RUNTIME_GENERATED
    })
    add("No runtime value placed in a dataset", not runtime_in_csv, "CRITICAL",
        "No server-generated value is treated as static test data." if not runtime_in_csv
        else f"Runtime value(s) leaked into a dataset (should be correlated): {', '.join(runtime_in_csv[:5])}")

    # 3. No business master data is correlated
    master_correlated = sorted({
        c.value for c in correlations if value_class.get(c.value) == ValueClass.BUSINESS_MASTER_DATA
    })
    add("No master data correlated", not master_correlated, "HIGH",
        "Existing business data is parameterized, not correlated." if not master_correlated
        else f"Master data correlated (should be a parameter): {', '.join(master_correlated[:5])}")

    # 4. Every extractor has a downstream consumer
    unused = [c.variable for c in correlations if not c.consumers]
    add("Every extractor is consumed", not unused, "MEDIUM",
        "No unused extractors." if not unused else f"Unused extractors: {', '.join(unused[:5])}")

    # 5. Missing correlations — server-issued, reused, but not correlated
    missing_runtime = sorted({
        v.value for v in classification.verdicts
        if v.classification == ValueClass.RUNTIME_GENERATED and v.consumers and v.value not in corr_values
    })
    add("No missing runtime correlations", not missing_runtime, "HIGH",
        "Every proven runtime dependency has an extractor." if not missing_runtime
        else f"Runtime values reused but not correlated: {', '.join(missing_runtime[:5])}")

    # 6. Ambiguous produced-and-reused values (review, not a hard failure)
    ambiguous = sorted({v.value for v in classification.unknowns() if v.consumers})
    add("No ambiguous reused values", not ambiguous, "MEDIUM",
        "No produced-and-reused value was left unclassified." if not ambiguous
        else f"Review: produced then reused but lifecycle unclear: {', '.join(ambiguous[:5])}")

    # 7. Session repeatable across iterations
    auth = detect_auth(cap)
    has_session = any(
        c.extractor == ExtractorType.COOKIE_MANAGER
        or c.producer_location.startswith("set-cookie:")
        or "token" in c.variable.lower() or "auth" in c.variable.lower() or "session" in c.variable.lower()
        for c in correlations
    )
    if auth.mechanisms:
        add("Authentication repeatable across iterations", has_session, "MEDIUM",
            "A session/token is extracted fresh each iteration." if has_session
            else f"Auth detected ({auth.primary}) but no session/token correlation — verify login replays.")

    # 8. Per-iteration data variation (iteration 2 uses a different row)
    thin = [d.name for d in plan.datasets if d.source == "entity" and d.row_count < 2]
    add("Distinct data available per iteration", not thin, "LOW",
        "Datasets have multiple rows for iteration variation." if not thin
        else f"Single-row dataset(s) — iterations reuse the same data: {', '.join(thin[:5])}")

    deducted = sum(_WEIGHT[f.severity] for f in findings if not f.passed)
    score = max(0, 100 - deducted)
    passed = score >= 70 and not any(
        (not f.passed) and f.severity in {"CRITICAL", "HIGH"} for f in findings
    )
    return ReplayReport(findings=findings, score=score, passed=passed)
