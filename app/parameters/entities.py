from __future__ import annotations

import zipfile
from datetime import datetime, timedelta
from pathlib import Path

from app.models import DataEntity, Parameter
from app.paths import OUTPUT_DIR
from app.patterns import (
    CONSTANT_FIELD_RE,
    DATE_FORMATS,
    EMAIL_SPLIT_RE,
    ENTITY_NAME_RULES,
    TRAILING_DIGITS_RE,
)


def parse_known_date(value: str) -> tuple[datetime, str] | None:
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt), fmt
        except ValueError:
            continue
    return None


def vary_business_value(name: str, value: str, row_index: int) -> str:
    if row_index == 0 or not value:
        return value
    if CONSTANT_FIELD_RE.search(name):
        return value
    parsed_date = parse_known_date(value)
    if parsed_date:
        dt, fmt = parsed_date
        try:
            return (dt + timedelta(days=row_index)).strftime(fmt)
        except (OverflowError, ValueError):
            return value
    if value.isdigit():
        return str(int(value) + row_index).zfill(len(value))
    email_match = EMAIL_SPLIT_RE.match(value)
    if email_match:
        local, domain = email_match.group("local"), email_match.group("domain")
        suffix_match = TRAILING_DIGITS_RE.match(local)
        if suffix_match and suffix_match.group("digits"):
            prefix, digits = suffix_match.group("prefix"), suffix_match.group("digits")
            local = f"{prefix}{str(int(digits) + row_index).zfill(len(digits))}"
        else:
            local = f"{local}{row_index + 1}"
        return f"{local}@{domain}"
    suffix_match = TRAILING_DIGITS_RE.match(value)
    if suffix_match and suffix_match.group("digits"):
        prefix, digits = suffix_match.group("prefix"), suffix_match.group("digits")
        return f"{prefix}{str(int(digits) + row_index).zfill(len(digits))}"
    return value


def partition_csv_parameters(parameters: list[Parameter]) -> tuple[list[Parameter], list[Parameter]]:
    csv_params = [p for p in parameters if p.csv_bound]
    udv_params = [p for p in parameters if not p.csv_bound]
    return csv_params, udv_params


def name_entity(params: list[Parameter]) -> str:
    combined = " ".join(p.name for p in params)
    for pattern, label in ENTITY_NAME_RULES:
        if pattern.search(combined):
            return label
    return "business_data"


def cluster_into_entities(csv_params: list[Parameter]) -> list[DataEntity]:
    if not csv_params:
        return []
    parent = list(range(len(csv_params)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[ri] = rj

    sampler_to_indices: dict[str, list[int]] = {}
    for index, param in enumerate(csv_params):
        for sampler_name in param.source_samplers:
            sampler_to_indices.setdefault(sampler_name, []).append(index)
    for indices in sampler_to_indices.values():
        for i in indices[1:]:
            union(indices[0], i)

    groups: dict[int, list[Parameter]] = {}
    for index, param in enumerate(csv_params):
        groups.setdefault(find(index), []).append(param)

    entities: list[DataEntity] = []
    used_names: set[str] = set()
    for group_params in groups.values():
        base_name = name_entity(group_params)
        name = base_name
        suffix = 2
        while name in used_names:
            name = f"{base_name}_{suffix}"
            suffix += 1
        used_names.add(name)
        alternate_rows: list[dict] = []
        for p in group_params:
            if p.alternate_rows:
                alternate_rows = p.alternate_rows
                break
        entities.append(DataEntity(
            name=name,
            parameters=sorted(group_params, key=lambda p: p.name),
            alternate_rows=alternate_rows,
        ))
    return sorted(entities, key=lambda e: e.name)


def write_entity_csv(result_id: str, entity: DataEntity, row_count: int = 5) -> Path:
    import csv as csv_module

    row_count = max(1, row_count)
    column_names = [p.name for p in entity.parameters]
    path = OUTPUT_DIR / f"test_data_{result_id}_{entity.name}.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv_module.writer(handle)
        rows_written = 0
        writer.writerow([p.value for p in entity.parameters])
        rows_written += 1
        for alt in entity.alternate_rows:
            if rows_written >= row_count:
                break
            writer.writerow([alt.get(name, p.value) for name, p in zip(column_names, entity.parameters)])
            rows_written += 1
        while rows_written < row_count:
            writer.writerow([vary_business_value(p.name, p.value, rows_written) for p in entity.parameters])
            rows_written += 1
    return path


def build_bundle(result_id: str, jmx_path: Path, extra_paths: list[Path]) -> Path:
    bundle_path = OUTPUT_DIR / f"self_healing_{result_id}.zip"
    with zipfile.ZipFile(bundle_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(jmx_path, arcname=jmx_path.name)
        for path in extra_paths:
            zf.write(path, arcname=path.name)
    return bundle_path
