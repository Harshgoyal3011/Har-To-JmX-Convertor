from __future__ import annotations

import json
import uuid
from pathlib import Path

from app.analyzer import (
    AnalyzerEngine, AIReviewLayer, DependencyGraph,
    ValueOriginClassifier, apply_value_origin_classification
)
from app.correlations import (
    reclassify_existing_business_entities,
    resolve_correlation_overlap,
)
from app.correlations.discover_enhanced import discover_correlations_enhanced
from app.jmx import build_jmx
from app.models import BuildResult
from app.parameters import (
    build_bundle,
    cluster_into_entities,
    partition_csv_parameters,
    write_entity_csv,
)
from app.parameters.discover_enhanced import discover_parameters_enhanced
from app.parameters.discover import detect_enterprise_apps
from app.paths import OUTPUT_DIR
from app.reports import (
    build_correlation_report,
    build_manual_review_report,
    build_parameterization_report,
    build_readme,
    build_replay_validation_report,
    build_summary,
)
from app.validation import (
    r10_quality_gate,
    r8_deduplicate_correlations,
    r8_verify_extractor_source,
    r9_detect_login_step,
    r9_validate_session_isolation,
    sanitize_workload_config,
)


def convert_har_v2(upload: bytes, config: dict[str, str] | None = None) -> BuildResult:
    """
    Refactored HAR conversion pipeline using the new architecture:
    HAR → Analyzer Engine → Dependency Graph → Parallel Processing → AI Review → JMX Builder → Reports
    """
    config = config or {}
    result_id = uuid.uuid4().hex[:10]
    
    # ============================================================================
    # STAGE 1: ANALYZER ENGINE
    # ============================================================================
    # Extract structure, transactions, value index, and entities from HAR
    analyzer = AnalyzerEngine()
    analysis_result = analyzer.analyze(upload)
    
    samplers = []
    total_entries = analysis_result.total_requests
    
    # Flatten transaction groups back to sampler list
    for tx_group in analysis_result.transaction_groups:
        samplers.extend(tx_group.samplers)
    
    if not samplers:
        raise ValueError(
            "No application/API traffic was found after filtering static assets. "
            "Capture a HAR while performing the business flow, including login and API calls."
        )
    
    # ============================================================================
    # STAGE 2: DEPENDENCY GRAPH CONSTRUCTION
    # ============================================================================
    # Discover correlations (using enhanced discovery) and build dependency graph
    correlations = discover_correlations_enhanced(samplers)
    dependency_graph = DependencyGraph(samplers)
    dependency_graph.build_from_correlations(correlations)
    
    # ============================================================================
    # STAGE 2B: VALUE ORIGIN CLASSIFICATION (OPTIMIZATION)
    # ============================================================================
    # Intelligent analysis: Is each value a correlation or parameter?
    # Example: product_id (from response) → CORRELATION vs product_name (from request) → PARAMETER
    value_origin_classifier = ValueOriginClassifier(samplers)
    
    # Apply classification intelligence
    correlations, promoted_parameters = reclassify_existing_business_entities(correlations, samplers)
    for sampler in samplers:
        sampler.correlations = [r for r in correlations if r.source_sampler == sampler.name]
    
    # ============================================================================
    # STAGE 3: PARALLEL PROCESSING STAGE (Correlation, Parameterization, Validation)
    # ============================================================================
    
    # --- PARAMETERIZATION ---
    parameters = discover_parameters_enhanced(samplers)
    
    # Apply value origin classification to avoid double-classification
    # (e.g., product_id: server-generated → correlation, product_name: user input → parameter)
    correlations, parameters, classification_conflicts = apply_value_origin_classification(
        correlations, parameters, value_origin_classifier.value_map
    )
    
    seen_keys = {(p.name, p.value) for p in promoted_parameters}
    parameters = promoted_parameters + [p for p in parameters if (p.name, p.value) not in seen_keys]
    
    parameters, overlap_removed = resolve_correlation_overlap(parameters, correlations)
    enterprise_apps = detect_enterprise_apps(samplers)
    csv_params, _udv_params = partition_csv_parameters(parameters)
    
    # --- VALIDATION ---
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
    
    # ============================================================================
    # STAGE 4: AI REVIEW LAYER
    # ============================================================================
    # Intelligent analysis and optimization recommendations
    ai_review = AIReviewLayer()
    review_result = ai_review.review(samplers, correlations, parameters, dependency_graph)
    
    # ============================================================================
    # STAGE 5: JMX BUILDER
    # ============================================================================
    jmx_path = build_jmx(
        result_id, samplers, parameters, correlations, config, clear_cookies, entities, csv_paths_by_entity
    )
    
    # ============================================================================
    # BUILD RESULT
    # ============================================================================
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
        script_ir=None,  # Already used analyzer result; not storing IR here
    )
    
    # ============================================================================
    # STAGE 6: REPORTS GENERATION
    # ============================================================================
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
    
    # Add AI review findings to summary
    summary_data = build_summary(result)
    summary_data["ai_review"] = {
        "optimization_score": review_result.optimization_score,
        "quality_metrics": {
            "correlation_coverage": review_result.quality_metrics.get("correlation_coverage", 0),
            "parameterization_ratio": review_result.quality_metrics.get("parameterization_ratio", 0),
            "avg_correlation_consumers": review_result.quality_metrics.get("avg_correlation_consumers", 0),
            "dependency_density": review_result.quality_metrics.get("dependency_density", 0),
            "avg_response_time_ms": review_result.quality_metrics.get("avg_response_time_ms", 0),
        },
        "findings": [
            {
                "category": f.category,
                "severity": f.severity,
                "message": f.message,
                "affected_items": f.affected_items,
            }
            for f in review_result.findings
        ],
        "findings_summary": {
            "total": len(review_result.findings),
            "critical": len([f for f in review_result.findings if f.severity == "Critical"]),
            "high": len([f for f in review_result.findings if f.severity == "High"]),
            "medium": len([f for f in review_result.findings if f.severity == "Medium"]),
            "low": len([f for f in review_result.findings if f.severity == "Low"]),
        },
        "recommendations": review_result.recommendations,
    }
    
    result.summary_path.write_text(json.dumps(summary_data, indent=2), encoding="utf-8")
    return result
