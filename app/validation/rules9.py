from __future__ import annotations

import re
from collections import Counter

from app.models import CorrectionRecord, CorrelationRule, DataEntity, Parameter, SamplerModel, ValidationResult
from app.patterns import EMAIL_VALUE_RE, GUID_RE, PHONE_VALUE_RE, TOKEN_NAME_RE, TOKEN_VALUE_RE
from app.utils import apply_variable
from app.validation.rules8 import rendered_sampler_text


def r9_detect_login_step(samplers: list[SamplerModel]) -> SamplerModel | None:
    for sampler in samplers:
        if re.search(r"/(login|auth|signin|sso|oauth|token)(/|$|\?)", sampler.path, re.IGNORECASE):
            if sampler.method in {"POST", "PUT"}:
                return sampler
    return None


def sanitize_workload_config(config: dict[str, str]) -> tuple[dict[str, str], int, list[CorrectionRecord]]:
    corrections: list[CorrectionRecord] = []

    def _clamp(raw: str, field_name: str, minimum: int, default: int) -> int:
        try:
            value = int(str(raw).strip())
        except (TypeError, ValueError):
            corrections.append(CorrectionRecord(
                rule="Rule 9",
                action=f"Corrected invalid {field_name}",
                detail=f"'{raw}' is not a valid whole number; using {default} instead.",
            ))
            return default
        if value < minimum:
            corrections.append(CorrectionRecord(
                rule="Rule 9",
                action=f"Corrected {field_name} below minimum",
                detail=f"{field_name} was {value}, which JMeter cannot run with "
                       f"(a Thread Group needs at least {minimum}); corrected to {minimum}.",
            ))
            return minimum
        return value

    threads = _clamp(config.get("threads", "1"), "concurrent users", minimum=1, default=1)
    loops = _clamp(config.get("loops", "1"), "iteration count", minimum=1, default=1)
    ramp = _clamp(config.get("ramp", "1"), "ramp-up seconds", minimum=0, default=1)

    sanitized = dict(config)
    sanitized["threads"] = str(threads)
    sanitized["loops"] = str(loops)
    sanitized["ramp"] = str(ramp)
    return sanitized, threads, corrections


def r9_validate_session_isolation(
    samplers: list[SamplerModel],
    correlations: list[CorrelationRule],
    clear_cookies: bool,
    login_sampler: SamplerModel | None,
) -> tuple[bool, list[CorrectionRecord], list[ValidationResult]]:
    corrections: list[CorrectionRecord] = []
    results: list[ValidationResult] = []
    corrected_clear_cookies = clear_cookies

    if login_sampler and not clear_cookies:
        corrected_clear_cookies = True
        corrections.append(CorrectionRecord(
            rule="Rule 9",
            action="Auto-enabled clearCookies",
            detail=f"Login step detected at '{login_sampler.name}'. Setting Cookie Manager clearEachIteration=true so each iteration starts with a fresh session, not stale cookies from the previous iteration.",
        ))

    results.append(ValidationResult(
        check="Rule 9 – Cookie Manager clears session between iterations",
        passed=corrected_clear_cookies or login_sampler is None,
        detail=(
            "clearEachIteration=true — each iteration begins with a clean session." if corrected_clear_cookies
            else "No login step detected; stale cookie risk is low. If sessions expire mid-test, enable clearEachIteration manually."
        ),
    ))

    has_auth_correlation = any(
        TOKEN_NAME_RE.search(r.variable)
        for r in correlations
    )
    results.append(ValidationResult(
        check="Rule 9 – Authentication is repeatable across iterations",
        passed=has_auth_correlation or login_sampler is None,
        detail=(
            "A session/token correlation was found; the login step will re-execute and re-extract on every iteration."
            if has_auth_correlation else
            "No session correlation found. If the application requires authentication, manually verify login flow."
        ),
    ))

    return corrected_clear_cookies, corrections, results


def r9_scan_hardcoded_tokens(
    samplers: list[SamplerModel],
    parameters: list[Parameter],
    correlations: list[CorrelationRule],
) -> list[ValidationResult]:
    results: list[ValidationResult] = []
    suspects: list[str] = []

    for sampler in samplers:
        rendered = rendered_sampler_text(sampler, parameters, correlations)
        for guid in set(GUID_RE.findall(rendered)):
            suspects.append(f"GUID {guid[:12]}... in '{sampler.name}'")
        for hname, hval in sampler.headers:
            if hname.lower() == "authorization" and hval:
                substituted = apply_variable(hval, parameters, correlations)
                if TOKEN_VALUE_RE.match(substituted) and "${" not in substituted:
                    suspects.append(f"Hardcoded Authorization token in '{sampler.name}' — should be correlated")

    results.append(ValidationResult(
        check="Rule 9 – No hardcoded runtime tokens remain",
        passed=not suspects,
        detail=(
            "No un-correlated dynamic values detected in the rendered script." if not suspects
            else f"{len(suspects)} suspect hardcoded value(s): {'; '.join(suspects[:4])}. Review before running at scale."
        ),
    ))
    return results


def r9_scan_hardcoded_business_inputs(
    samplers: list[SamplerModel],
    parameters: list[Parameter],
    correlations: list[CorrelationRule],
) -> list[ValidationResult]:
    results: list[ValidationResult] = []
    suspects: list[str] = []

    for sampler in samplers:
        if sampler.method not in {"POST", "PUT", "PATCH"}:
            continue
        for _name, value in sampler.post_params:
            substituted = apply_variable(value, parameters, correlations)
            if "${" in substituted:
                continue
            if EMAIL_VALUE_RE.match(value or "") or PHONE_VALUE_RE.match(value or ""):
                suspects.append(f"'{value}' in '{sampler.name}'")
        if sampler.post_body:
            for match in re.finditer(r'"[^"]*"\s*:\s*"([^"]+)"', sampler.post_body):
                value = match.group(1)
                if (EMAIL_VALUE_RE.match(value) or PHONE_VALUE_RE.match(value)) and "${" not in apply_variable(value, parameters, correlations):
                    suspects.append(f"'{value}' in '{sampler.name}'")

    results.append(ValidationResult(
        check="No business inputs remain hardcoded (value-shape scan)",
        passed=not suspects,
        detail=(
            "No email- or phone-shaped literals were found hardcoded in a request after parameterization."
            if not suspects else
            f"{len(suspects)} business-data-shaped value(s) appear hardcoded, not parameterized: {'; '.join(suspects[:4])}"
        ),
    ))
    return results


def r9_validate_concurrent_data_isolation(
    entities: list[DataEntity],
    requested_threads: int,
    csv_row_count: int,
) -> list[ValidationResult]:
    results: list[ValidationResult] = []
    if not entities:
        return results

    has_credential_entity = any(
        any(re.search(r"username|email|user_?id", p.name, re.IGNORECASE) for p in e.parameters)
        for e in entities
    )
    sufficient = csv_row_count >= requested_threads
    results.append(ValidationResult(
        check="Rule 9 – Sufficient test data rows for concurrent users",
        passed=sufficient or not has_credential_entity,
        detail=(
            f"CSV has {csv_row_count} rows for {requested_threads} concurrent users — each user gets a unique data row."
            if sufficient else
            f"CSV has {csv_row_count} rows but {requested_threads} concurrent users are configured. "
            f"Users {csv_row_count + 1}–{requested_threads} will reuse rows — if the application enforces unique sessions, increase CSV rows manually."
        ),
    ))
    return results


def validate_transaction_grouping(samplers: list[SamplerModel]) -> list[ValidationResult]:
    results: list[ValidationResult] = []
    if not samplers:
        return results

    seen_blocks: dict[str, int] = {}
    fragmented: list[str] = []
    current = None
    for sampler in samplers:
        if sampler.transaction != current:
            if sampler.transaction in seen_blocks:
                fragmented.append(sampler.transaction)
            seen_blocks[sampler.transaction] = seen_blocks.get(sampler.transaction, 0) + 1
            current = sampler.transaction

    results.append(ValidationResult(
        check="Supporting requests are grouped contiguously by user action",
        passed=not fragmented,
        detail=(
            "Every transaction's requests are contiguous — no user action was split and re-merged elsewhere."
            if not fragmented else
            f"Transaction name(s) reappear in non-contiguous blocks, which usually means requests from one user "
            f"action got separated: {', '.join(sorted(set(fragmented))[:4])}"
        ),
    ))

    sizes = Counter(s.transaction for s in samplers)
    oversized = [(name, count) for name, count in sizes.items() if count > 12]
    results.append(ValidationResult(
        check="No transaction bundles an implausibly large number of requests",
        passed=not oversized,
        detail=(
            "All transactions have a request count consistent with a single user action."
            if not oversized else
            f"{len(oversized)} transaction(s) contain more than 12 requests, which may mean multiple distinct "
            f"user actions were merged (common in SPA captures with no page markers): "
            f"{', '.join(f'{n} ({c} requests)' for n, c in oversized[:3])}"
        ),
    ))
    return results
