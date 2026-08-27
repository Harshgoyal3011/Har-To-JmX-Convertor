from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from har2jmx.ir.models import ScriptIR


@dataclass
class CorrelationRule:
    variable: str
    source_sampler: str
    pattern: str
    field: str = "body"
    value: str = ""
    confidence: str = "Medium"
    reason: str = ""
    extractor: str = "regex"
    json_key: str = ""
    classification: str = "B"
    origin: str = ""
    consumers: tuple = ()
    sibling_fields: tuple = ()
    producer_sampler_path: str = ""
    producer_method: str = ""
    producer_status: str = ""


@dataclass
class Parameter:
    name: str
    value: str
    occurrences: int
    reason: str
    confidence: str = "Medium"
    csv_bound: bool = False
    source_samplers: frozenset[str] = field(default_factory=frozenset)
    classification: str = "A"
    alternate_rows: list = field(default_factory=list)


@dataclass
class SamplerModel:
    name: str
    method: str
    url: str
    protocol: str
    domain: str
    port: str
    path: str
    query: list[tuple[str, str]]
    headers: list[tuple[str, str]]
    cookies: list[tuple[str, str]]
    response_headers: list[tuple[str, str]]
    post_params: list[tuple[str, str]]
    post_body: str
    mime_type: str
    transaction: str
    status: int | str
    time_ms: int
    response_text: str = ""
    correlations: list[CorrelationRule] = field(default_factory=list)


@dataclass
class ValidationResult:
    check: str
    passed: bool
    detail: str


@dataclass
class CorrectionRecord:
    rule: str
    action: str
    detail: str


@dataclass
class QualityGateResult:
    passed: bool
    score: int
    checks: list[ValidationResult]
    corrections: list[CorrectionRecord]


@dataclass
class DataEntity:
    name: str
    parameters: list[Parameter]
    alternate_rows: list = field(default_factory=list)


@dataclass
class BuildResult:
    test_name: str
    samplers: list[SamplerModel]
    parameters: list[Parameter]
    correlations: list[CorrelationRule]
    total_entries: int
    jmx_path: Path
    summary_path: Path
    thread_count: str = "1"
    loops: str = "1"
    ramp_time: str = "1"
    clear_cookies: bool = False
    csv_paths: list[Path] = field(default_factory=list)
    entities: list[DataEntity] = field(default_factory=list)
    bundle_path: Path | None = None
    enterprise_apps: list[str] = field(default_factory=list)
    overlap_removed: int = 0
    csv_row_count: int = 0
    validation_results: list[ValidationResult] = field(default_factory=list)
    quality_gate_score: int = 0
    quality_gate_passed: bool = False
    auto_corrections: list[CorrectionRecord] = field(default_factory=list)
    report_paths: list[Path] = field(default_factory=list)
    # Phase 1 IR handle — populated by the pipeline; engines still use samplers today
    script_ir: ScriptIR | None = None
