from __future__ import annotations

import json
import uuid
from pathlib import Path

from har2jmx.correlations import (
    discover_correlations,
    reclassify_existing_business_entities,
    resolve_correlation_overlap,
)
from har2jmx.har import build_script_ir, read_har
from har2jmx.ir.compat import script_ir_to_samplers
from har2jmx.jmx import build_jmx
from har2jmx.models import BuildResult
from har2jmx.parameters import (
    build_bundle,
    cluster_into_entities,
    detect_enterprise_apps,
    discover_parameters,
    partition_csv_parameters,
    write_entity_csv,
)
from har2jmx.paths import OUTPUT_DIR
from har2jmx.reports import (
    build_correlation_report,
    build_manual_review_report,
    build_parameterization_report,
    build_readme,
    build_replay_validation_report,
    build_summary,
)
from har2jmx.validation import (
    r10_quality_gate,
    r8_deduplicate_correlations,
    r8_verify_extractor_source,
    r9_detect_login_step,
    r9_validate_session_isolation,
    sanitize_workload_config,
)


def convert_har(upload: bytes, config: dict[str, str] | None = None) -> BuildResult:
    config = config or {}
    result_id = uuid.uuid4().hex[:10]
    har = read_har(upload)
    script_ir = build_script_ir(har)
    total_entries = script_ir.total_har_entries
    # Phase 1: IR is built first; SamplerModel remains the working surface for engines
    samplers = script_ir_to_samplers(script_ir)
    if not samplers:
        raise ValueError(
            "No application/API traffic was found after filtering static assets. "
            "Capture a HAR while performing the business flow, including login and API calls."
        )
    parameters = discover_parameters(samplers)
    correlations = discover_correlations(samplers)

    correlations, promoted_parameters = reclassify_existing_business_entities(correlations, samplers)
    for sampler in samplers:
        sampler.correlations = [r for r in correlations if r.source_sampler == sampler.name]

    seen_keys = {(p.name, p.value) for p in promoted_parameters}
    parameters = promoted_parameters + [p for p in parameters if (p.name, p.value) not in seen_keys]

    parameters, overlap_removed = resolve_correlation_overlap(parameters, correlations)
    enterprise_apps = detect_enterprise_apps(samplers)
    csv_params, _udv_params = partition_csv_parameters(parameters)

    config, requested_threads, workload_corrections = sanitize_workload_config(config)

    csv_row_count = max(5, min(requested_threads, 50))
    entities = cluster_into_entities(csv_params)
    csv_paths_by_entity: dict[str, Path] = {
        entity.name: write_entity_csv(result_id, entity, csv_row_count) for entity in entities
    }
    csv_paths = list(csv_paths_by_entity.values())

    correlations, r8_dedup_corrections = r8_deduplicate_correlations(correlations, samplers)
    r8_source_corrections = r8_verify_extractor_source(correlations, samplers)

    login_sampler = r9_detect_login_step(samplers)
    user_requested_clear = str(config.get("clearCookies", "false")).lower() in {"1", "true", "yes"}
    clear_cookies, r9_session_corrections, _ = r9_validate_session_isolation(
        samplers, correlations, user_requested_clear, login_sampler
    )

    quality_gate = r10_quality_gate(
        samplers, parameters, correlations, entities,
        clear_cookies, requested_threads, csv_row_count,
        overlap_removed,
    )
    all_corrections = (
        workload_corrections
        + r8_dedup_corrections
        + r8_source_corrections
        + r9_session_corrections
        + quality_gate.corrections
    )

    validation_results = quality_gate.checks

    jmx_path = build_jmx(
        result_id, samplers, parameters, correlations, config, clear_cookies, entities, csv_paths_by_entity
    )
    result = BuildResult(
        test_name=jmx_path.stem,
        samplers=samplers,
        parameters=parameters,
        correlations=correlations,
        total_entries=total_entries,
        jmx_path=jmx_path,
        summary_path=OUTPUT_DIR / f"summary_{result_id}.json",
        thread_count=str(config.get("threads", "1") or "1"),
        loops=str(config.get("loops", "1") or "1"),
        ramp_time=str(config.get("ramp", "1") or "1"),
        clear_cookies=clear_cookies,
        csv_paths=csv_paths,
        entities=entities,
        bundle_path=None,
        enterprise_apps=enterprise_apps,
        overlap_removed=overlap_removed,
        csv_row_count=csv_row_count if csv_paths else 0,
        validation_results=validation_results,
        quality_gate_score=quality_gate.score,
        quality_gate_passed=quality_gate.passed,
        auto_corrections=all_corrections,
        script_ir=script_ir,
    )

    report_specs: list[tuple[str, str | None]] = [
        (f"CORRELATION_REPORT_{result_id}.md", build_correlation_report(result)),
        (f"PARAMETERIZATION_REPORT_{result_id}.md", build_parameterization_report(result)),
        (f"REPLAY_VALIDATION_REPORT_{result_id}.md", build_replay_validation_report(result)),
        (f"MANUAL_REVIEW_REPORT_{result_id}.md", build_manual_review_report(result)),
    ]
    report_paths: list[Path] = []
    for filename, content in report_specs:
        if content is None:
            continue
        path = OUTPUT_DIR / filename
        path.write_text(content, encoding="utf-8")
        report_paths.append(path)

    readme_path = OUTPUT_DIR / f"README_{result_id}.md"
    readme_path.write_text(build_readme(result, [p.name for p in report_paths]), encoding="utf-8")
    report_paths.append(readme_path)

    bundle_path = build_bundle(result_id, jmx_path, csv_paths + report_paths)
    result.bundle_path = bundle_path
    result.report_paths = report_paths

    result.summary_path.write_text(json.dumps(build_summary(result), indent=2), encoding="utf-8")
    return result
