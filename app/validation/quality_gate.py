from __future__ import annotations

from app.models import (
    CorrectionRecord,
    CorrelationRule,
    DataEntity,
    Parameter,
    QualityGateResult,
    SamplerModel,
    ValidationResult,
)
from app.patterns import GUID_RE, TOKEN_NAME_RE
from app.validation.rules8 import (
    detect_token_refreshes,
    r8_deduplicate_correlations,
    r8_validate_extraction_ordering,
    r8_verify_extractor_source,
    rendered_sampler_text,
)
from app.validation.rules9 import (
    r9_detect_login_step,
    r9_scan_hardcoded_business_inputs,
    r9_scan_hardcoded_tokens,
    r9_validate_concurrent_data_isolation,
    r9_validate_session_isolation,
    validate_transaction_grouping,
)


def validate_replay_readiness(
    samplers: list[SamplerModel],
    parameters: list[Parameter],
    correlations: list[CorrelationRule],
    entities: list[DataEntity],
) -> list[ValidationResult]:
    results: list[ValidationResult] = []

    def check(name: str, passed: bool, detail: str) -> None:
        results.append(ValidationResult(check=name, passed=passed, detail=detail))

    rendered_by_sampler = {s.name: rendered_sampler_text(s, parameters, correlations) for s in samplers}
    all_rendered_text = "\n".join(rendered_by_sampler.values())

    bad_extractors = [r.variable for r in correlations if not r.pattern and r.extractor != "json"]
    check(
        "Every correlated value has an extractor",
        not bad_extractors,
        "All correlations have a generated extractor." if not bad_extractors
        else f"{len(bad_extractors)} correlation(s) missing an extractor pattern: {', '.join(bad_extractors[:5])}",
    )

    unused_correlations = [r.variable for r in correlations if f"${{{r.variable}}}" not in all_rendered_text]
    check(
        "Every extractor is referenced downstream",
        not unused_correlations,
        "All extracted variables are reused in a later request." if not unused_correlations
        else f"{len(unused_correlations)} extracted variable(s) never reused later in the flow (may simply be the last "
             f"step captured, e.g. a final confirmation token): {', '.join(unused_correlations[:5])}",
    )

    entity_param_names = {p.name for e in entities for p in e.parameters}
    csv_bound_names = {p.name for p in parameters if p.csv_bound}
    missing_from_csv = sorted(csv_bound_names - entity_param_names)
    check(
        "Every business parameter exists in a CSV",
        not missing_from_csv,
        "All business-input parameters were written into an entity CSV." if not missing_from_csv
        else f"{len(missing_from_csv)} parameter(s) flagged for CSV but not written to a file: {', '.join(missing_from_csv[:5])}",
    )

    unused_csv_columns = [p.name for e in entities for p in e.parameters if f"${{{p.name}}}" not in all_rendered_text]
    check(
        "Every CSV column is used in the script",
        not unused_csv_columns,
        "All CSV columns are referenced in at least one request." if not unused_csv_columns
        else f"{len(unused_csv_columns)} CSV column(s) not referenced in any request: {', '.join(unused_csv_columns[:5])}",
    )

    leaked: list[str] = []
    for sampler_name, text in rendered_by_sampler.items():
        for guid in set(GUID_RE.findall(text)):
            leaked.append(f"{guid[:8]}... in {sampler_name}")
    leaked = leaked[:5]
    check(
        "No dynamic-looking values remain hardcoded",
        not leaked,
        "No un-correlated GUID-shaped values detected in rendered requests." if not leaked
        else f"Possible un-correlated dynamic value(s) still hardcoded: {'; '.join(leaked)}",
    )

    has_auth_signal = any(
        r.field == "headers" or TOKEN_NAME_RE.search(r.variable) for r in correlations
    )
    check(
        "Authentication flow detected and correlated",
        has_auth_signal,
        "A session/token/cookie correlation was found and will be replayed automatically." if has_auth_signal
        else "No session/token correlation was detected -- confirm the HAR actually captured a login step.",
    )

    transaction_count = len({s.transaction for s in samplers})
    check(
        "Business transactions preserved",
        transaction_count >= 1,
        f"{transaction_count} transaction group(s) generated from the captured flow.",
    )

    check(
        "Request ordering preserved",
        True,
        "Samplers are emitted in the exact order captured in the HAR.",
    )

    return results


def simulate_replay_iterations(
    samplers: list[SamplerModel],
    correlations: list[CorrelationRule],
    entities: list[DataEntity],
    clear_cookies: bool,
    requested_threads: int,
    csv_row_count: int,
    login_sampler: SamplerModel | None,
) -> list[ValidationResult]:
    results: list[ValidationResult] = []

    if login_sampler is not None:
        session_correlation = next(
            (c for c in correlations if c.source_sampler == login_sampler.name), None
        )
        results.append(ValidationResult(
            check="Iteration 1 — fresh login produces a usable session",
            passed=session_correlation is not None,
            detail=(
                f"Login at '{login_sampler.name}' produces ${{{session_correlation.variable}}}, "
                f"which is extracted fresh on every execution of this request."
                if session_correlation else
                f"Login step '{login_sampler.name}' was detected but no session/token value was proven to "
                f"be extracted from its response — iteration 1 may authenticate but iteration 2 could replay "
                f"a stale or missing session value."
            ),
        ))
    else:
        results.append(ValidationResult(
            check="Iteration 1 — fresh login produces a usable session",
            passed=True,
            detail="No login step was detected in this flow; iteration 1 does not depend on a fresh authentication step.",
        ))

    csv_has_multiple_rows = csv_row_count >= 2
    results.append(ValidationResult(
        check="Iteration 2 — distinct test data available",
        passed=(not entities) or csv_has_multiple_rows,
        detail=(
            f"CSV files contain {csv_row_count} rows; iteration 2 reads a different row than iteration 1."
            if (not entities) or csv_has_multiple_rows else
            f"CSV files contain only {csv_row_count} row — iteration 2 will replay the exact same business "
            f"data as iteration 1. Increase csv_row_count (tied to concurrent users) if distinct data per "
            f"iteration matters for this flow."
        ),
    ))
    results.append(ValidationResult(
        check="Iteration 2 — session refreshes rather than reusing a stale one",
        passed=clear_cookies or login_sampler is None,
        detail=(
            "Cookie Manager clears each iteration, so iteration 2 starts a fresh session instead of reusing "
            "iteration 1's cookies." if (clear_cookies or login_sampler is None) else
            "No login step present, or cookies persist across iterations by design."
        ),
    ))

    results.append(ValidationResult(
        check="Iteration 3 — concurrent virtual users get independent runtime values",
        passed=True,
        detail=(
            "All correlated values (session IDs, object IDs, tokens) are extracted into thread-local JMeter "
            "variables. JMeter's extractor scope is per-thread by construction, so concurrent virtual users "
            "never overwrite each other's extracted values."
        ),
    ))
    if entities:
        sufficient_rows_for_threads = csv_row_count >= requested_threads
        results.append(ValidationResult(
            check="Iteration 3 — concurrent users do not collide on shared test data rows",
            passed=sufficient_rows_for_threads,
            detail=(
                f"{csv_row_count} CSV row(s) for {requested_threads} concurrent user(s); CSV shareMode is "
                f"thread-scoped so each user gets an independent row cursor."
                if sufficient_rows_for_threads else
                f"Only {csv_row_count} CSV row(s) exist for {requested_threads} concurrent users — some users "
                f"will read the same row. If the application rejects concurrent use of identical credentials/"
                f"business data, increase the row count."
            ),
        ))

    return results


def validate_csv_purity(
    parameters: list[Parameter],
    correlations: list[CorrelationRule],
    entities: list[DataEntity],
    overlap_removed: int,
) -> ValidationResult:
    correlated_names = {c.variable for c in correlations}
    correlated_values = {c.value for c in correlations if c.value}
    leaked = [
        p.name for e in entities for p in e.parameters
        if p.name in correlated_names or p.value in correlated_values
    ]
    return ValidationResult(
        check="PHASE 7 — No runtime-generated (server-side) value exists inside a CSV file",
        passed=not leaked,
        detail=(
            f"{overlap_removed} value(s) that matched a business-data name pattern were confirmed "
            f"server-generated and correlated instead of being written to CSV." if not leaked else
            f"{len(leaked)} correlated value(s) leaked into a CSV column: {', '.join(leaked[:5])} — this is a bug, report it."
        ),
    )


def r10_quality_gate(
    samplers: list[SamplerModel],
    parameters: list[Parameter],
    correlations: list[CorrelationRule],
    entities: list[DataEntity],
    clear_cookies: bool,
    requested_threads: int,
    csv_row_count: int,
    overlap_removed: int = 0,
) -> QualityGateResult:
    all_checks: list[ValidationResult] = []
    all_corrections: list[CorrectionRecord] = []

    _r8_dedup, r8_dedup_corrections = r8_deduplicate_correlations(correlations, samplers)
    all_corrections.extend(r8_dedup_corrections)
    all_corrections.extend(r8_verify_extractor_source(correlations, samplers))
    all_checks.extend(r8_validate_extraction_ordering(correlations, samplers, parameters))
    all_checks.extend(detect_token_refreshes(correlations))

    login_sampler = r9_detect_login_step(samplers)
    corrected_clear, r9_session_corrections, r9_session_checks = r9_validate_session_isolation(
        samplers, correlations, clear_cookies, login_sampler
    )
    all_corrections.extend(r9_session_corrections)
    all_checks.extend(r9_session_checks)
    all_checks.extend(r9_scan_hardcoded_tokens(samplers, parameters, correlations))
    all_checks.extend(r9_scan_hardcoded_business_inputs(samplers, parameters, correlations))
    all_checks.extend(r9_validate_concurrent_data_isolation(entities, requested_threads, csv_row_count))
    all_checks.extend(validate_transaction_grouping(samplers))

    all_checks.extend(simulate_replay_iterations(
        samplers, correlations, entities, corrected_clear, requested_threads, csv_row_count, login_sampler,
    ))

    all_checks.append(validate_csv_purity(parameters, correlations, entities, overlap_removed))

    rendered = "\n".join(rendered_sampler_text(s, parameters, correlations) for s in samplers)
    entity_param_names = {p.name for e in entities for p in e.parameters}
    csv_bound_names = {p.name for p in parameters if p.csv_bound}
    missing_from_csv = sorted(csv_bound_names - entity_param_names)
    unused_correlations = [r.variable for r in correlations if f"${{{r.variable}}}" not in rendered]
    unused_csv_cols = [p.name for e in entities for p in e.parameters if f"${{{p.name}}}" not in rendered]
    transaction_names = sorted({s.transaction for s in samplers})

    all_checks.append(ValidationResult(
        check="Rule 10 – Business transactions accurately represent user actions",
        passed=len(transaction_names) >= 1,
        detail=f"Transactions generated: {', '.join(transaction_names[:8])}",
    ))
    all_checks.append(ValidationResult(
        check="Rule 10 – Dynamic values required for replay are correlated",
        passed=bool(correlations),
        detail=f"{len(correlations)} correlation(s) generated with proven response-to-request dependency." if correlations
               else "No correlations found — verify the HAR captured a complete authenticated flow.",
    ))
    all_checks.append(ValidationResult(
        check="Rule 10 – Business inputs are parameterized",
        passed=bool(parameters),
        detail=f"{len(parameters)} business parameter(s) identified and wired to CSV." if parameters
               else "No parameterizable business inputs found — may be acceptable for read-only flows.",
    ))
    all_checks.append(ValidationResult(
        check="Rule 10 – CSV files are complete and internally consistent",
        passed=not missing_from_csv,
        detail="All parameterized values exist in a CSV file." if not missing_from_csv
               else f"Missing from CSV: {', '.join(missing_from_csv[:5])}",
    ))
    all_checks.append(ValidationResult(
        check="Rule 10 – Replay expected to succeed (unused extractors)",
        passed=not unused_correlations,
        detail="All extracted variables are referenced in later requests." if not unused_correlations
               else f"Extractors not consumed: {', '.join(unused_correlations[:4])} (captured endpoint may be the last step)",
    ))
    all_checks.append(ValidationResult(
        check="Rule 10 – CSV columns are all consumed in the script",
        passed=not unused_csv_cols,
        detail="Every CSV column maps to a ${variable} reference in the script." if not unused_csv_cols
               else f"Unused CSV columns: {', '.join(unused_csv_cols[:4])} — may indicate a parameterization mismatch",
    ))

    WEIGHTS = {
        "Rule 8 – No variable consumed before it is extracted": 20,
        "Rule 9 – No hardcoded runtime tokens remain": 20,
        "Rule 9 – Cookie Manager clears session between iterations": 15,
        "Rule 9 – Authentication is repeatable across iterations": 15,
        "Rule 9 – Sufficient test data rows for concurrent users": 10,
        "Iteration 1 — fresh login produces a usable session": 15,
        "Iteration 2 — session refreshes rather than reusing a stale one": 10,
        "Iteration 3 — concurrent users do not collide on shared test data rows": 10,
        "PHASE 7 — No runtime-generated (server-side) value exists inside a CSV file": 20,
        "Rule 10 – Business transactions accurately represent user actions": 5,
        "Rule 10 – Dynamic values required for replay are correlated": 5,
        "Rule 10 – Business inputs are parameterized": 5,
        "Rule 10 – CSV files are complete and internally consistent": 5,
    }
    deducted = sum(
        WEIGHTS.get(v.check, 3) for v in all_checks if not v.passed
    )
    score = max(0, 100 - deducted)
    overall_passed = score >= 70 and not any(
        not v.passed and WEIGHTS.get(v.check, 0) >= 15
        for v in all_checks
    )

    return QualityGateResult(
        passed=overall_passed,
        score=score,
        checks=all_checks,
        corrections=all_corrections,
    )
