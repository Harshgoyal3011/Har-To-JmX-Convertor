from __future__ import annotations

from app.models import CorrectionRecord, CorrelationRule, Parameter, SamplerModel, ValidationResult
from app.utils import apply_variable


def rendered_sampler_text(sampler: SamplerModel, parameters: list[Parameter], correlations: list[CorrelationRule]) -> str:
    parts = [apply_variable(sampler.post_body or "", parameters, correlations)]
    for _name, value in sampler.query + sampler.post_params + sampler.headers:
        parts.append(apply_variable(value, parameters, correlations))
    return "\n".join(parts)


def raw_sampler_text(sampler: SamplerModel) -> str:
    parts = [sampler.post_body or ""]
    for _name, value in sampler.query + sampler.post_params + sampler.headers:
        parts.append(value or "")
    return "\n".join(parts)


def r8_deduplicate_correlations(
    correlations: list[CorrelationRule],
    samplers: list[SamplerModel],
) -> tuple[list[CorrelationRule], list[CorrectionRecord]]:
    records: list[CorrectionRecord] = []
    sampler_index = {s.name: i for i, s in enumerate(samplers)}
    seen: dict[tuple[str, str], CorrelationRule] = {}
    for rule in correlations:
        key = (rule.variable, rule.value)
        existing = seen.get(key)
        if existing is None:
            seen[key] = rule
        else:
            existing_idx = sampler_index.get(existing.source_sampler, 999)
            new_idx = sampler_index.get(rule.source_sampler, 999)
            if new_idx < existing_idx:
                records.append(CorrectionRecord(
                    rule="Rule 8",
                    action="Replaced true duplicate extractor with earlier-source extractor",
                    detail=f"${{{rule.variable}}} (same value): kept source '{rule.source_sampler}' (index {new_idx}), dropped '{existing.source_sampler}' (index {existing_idx})",
                ))
                seen[key] = rule
            else:
                records.append(CorrectionRecord(
                    rule="Rule 8",
                    action="Dropped true duplicate extractor",
                    detail=f"${{{rule.variable}}} (same value): kept source '{existing.source_sampler}', dropped later duplicate from '{rule.source_sampler}'",
                ))
    deduped = list(seen.values())
    deduped.sort(key=lambda r: sampler_index.get(r.source_sampler, 999))
    for sampler in samplers:
        sampler.correlations = [r for r in deduped if r.source_sampler == sampler.name]
    return deduped, records


def detect_token_refreshes(correlations: list[CorrelationRule]) -> list[ValidationResult]:
    by_variable: dict[str, list[CorrelationRule]] = {}
    for rule in correlations:
        by_variable.setdefault(rule.variable, []).append(rule)
    results: list[ValidationResult] = []
    refreshed = {name: rules for name, rules in by_variable.items() if len(rules) > 1}
    if refreshed:
        for name, rules in refreshed.items():
            sources = " -> ".join(r.source_sampler for r in rules)
            results.append(ValidationResult(
                check=f"Token refresh preserved for ${{{name}}}",
                passed=True,
                detail=f"{len(rules)} extraction points kept (not collapsed as duplicates): {sources}. "
                       f"Each request after a given point uses whichever value was most recently extracted.",
            ))
    return results


def r8_verify_extractor_source(
    correlations: list[CorrelationRule],
    samplers: list[SamplerModel],
) -> list[CorrectionRecord]:
    records: list[CorrectionRecord] = []
    sampler_map = {s.name: s for s in samplers}

    for rule in correlations:
        source = sampler_map.get(rule.source_sampler)
        if source is None:
            continue
        response_text = source.response_text or ""
        header_text = " ".join(f"{n}: {v}" for n, v in source.response_headers)
        combined = response_text + " " + header_text
        if rule.value and rule.value in combined:
            continue

        for sampler in samplers:
            resp = (sampler.response_text or "") + " ".join(
                f"{n}: {v}" for n, v in sampler.response_headers
            )
            if rule.value in resp:
                old_source = rule.source_sampler
                rule.source_sampler = sampler.name
                for s in samplers:
                    s.correlations = [r for r in s.correlations if r is not rule]
                sampler.correlations.append(rule)
                records.append(CorrectionRecord(
                    rule="Rule 8",
                    action="Auto-corrected extractor source",
                    detail=f"${{{rule.variable}}}: moved extractor from '{old_source}' to '{sampler.name}' (actual response source)",
                ))
                break
    return records


def r8_validate_extraction_ordering(
    correlations: list[CorrelationRule],
    samplers: list[SamplerModel],
    parameters: list[Parameter],
) -> list[ValidationResult]:
    results: list[ValidationResult] = []
    sampler_index = {s.name: i for i, s in enumerate(samplers)}
    violations: list[str] = []

    for rule in correlations:
        extract_at = sampler_index.get(rule.source_sampler, -1)
        if extract_at < 0 or not rule.value:
            continue
        for earlier_sampler in samplers[:extract_at]:
            if rule.value in raw_sampler_text(earlier_sampler):
                violations.append(
                    f"${{{rule.variable}}}'s value consumed in '{earlier_sampler.name}' "
                    f"(index {sampler_index[earlier_sampler.name]}) before its extraction "
                    f"at '{rule.source_sampler}' (index {extract_at})"
                )

    results.append(ValidationResult(
        check="Rule 8 – No variable consumed before it is extracted",
        passed=not violations,
        detail="All extracted variables are consumed only after their extraction point." if not violations
               else f"{len(violations)} ordering violation(s): {'; '.join(violations[:3])}",
    ))
    return results
