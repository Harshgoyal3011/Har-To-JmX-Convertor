from __future__ import annotations

import json
from typing import Any

from har2jmx.models import CorrelationRule, Parameter, SamplerModel
from har2jmx.patterns import CREATION_VERB_RE, EXISTING_ENTITY_VERB_RE
from har2jmx.utils import variable_name


def classify_producer_as_existing_entity(sampler: SamplerModel) -> bool:
    if str(sampler.status).strip() == "201":
        return False
    if CREATION_VERB_RE.search(sampler.path):
        return False
    if sampler.method == "GET":
        return True
    if sampler.method == "POST" and EXISTING_ENTITY_VERB_RE.search(sampler.path):
        return True
    return False


def find_sibling_records(producer_sampler: SamplerModel, bare_key: str, id_value: str) -> list[dict]:
    if not producer_sampler.response_text:
        return []
    try:
        body = json.loads(producer_sampler.response_text)
    except (json.JSONDecodeError, ValueError):
        return []

    matches: list[list[dict]] = []

    def _walk(obj: Any) -> None:
        if isinstance(obj, list):
            dict_items = [item for item in obj if isinstance(item, dict) and bare_key in item]
            if len(dict_items) >= 2 and any(str(item.get(bare_key)) == id_value for item in dict_items):
                matches.append(dict_items)
            for item in obj:
                _walk(item)
        elif isinstance(obj, dict):
            for v in obj.values():
                _walk(v)

    _walk(body)
    return matches[0] if matches else []


def reclassify_existing_business_entities(
    correlations: list[CorrelationRule],
    samplers: list[SamplerModel],
) -> tuple[list[CorrelationRule], list[Parameter]]:
    remaining: list[CorrelationRule] = []
    promoted: list[Parameter] = []
    
    # Pre-build sampler lookup dict for O(1) access instead of O(n) linear search
    sampler_by_name: dict[str, SamplerModel] = {s.name: s for s in samplers}

    for rule in correlations:
        producer_sampler = sampler_by_name.get(rule.source_sampler)
        is_existing_entity = (
            rule.classification == "B"
            and producer_sampler is not None
            and classify_producer_as_existing_entity(producer_sampler)
        )
        if not is_existing_entity:
            remaining.append(rule)
            continue

        source_set = frozenset({rule.source_sampler})
        bare_key = (rule.json_key or rule.variable).split(".")[-1]
        sibling_records = find_sibling_records(producer_sampler, bare_key, rule.value) if producer_sampler else []
        alternate_rows: list[dict] = []
        if len(sibling_records) >= 2:
            for record in sibling_records:
                if str(record.get(bare_key)) == rule.value:
                    continue
                row = {rule.variable: str(record.get(bare_key, ""))}
                for sib_name, sib_value in rule.sibling_fields:
                    if sib_name in record:
                        row[variable_name(sib_name)] = str(record[sib_name])
                alternate_rows.append(row)

        promoted.append(Parameter(
            name=rule.variable,
            value=rule.value,
            occurrences=len(rule.consumers) or 1,
            reason=(
                f"Existing business entity selected from '{rule.source_sampler}' "
                f"({producer_sampler.method} — reads existing data, not created this session); "
                f"another user could select a different one, so this varies with test data."
            ),
            confidence=rule.confidence,
            csv_bound=True,
            source_samplers=source_set,
            classification="A",
            alternate_rows=alternate_rows,
        ))
        for sib_name, sib_value in rule.sibling_fields:
            sib_str = str(sib_value)
            if not sib_str or len(sib_str) > 200:
                continue
            promoted.append(Parameter(
                name=variable_name(sib_name),
                value=sib_str,
                occurrences=1,
                reason=f"Attribute of the same selected record as ${{{rule.variable}}} (from '{rule.source_sampler}') — kept in the same row to preserve the pairing.",
                confidence="Medium",
                csv_bound=True,
                source_samplers=source_set,
                classification="A",
            ))

    return remaining, promoted


def resolve_correlation_overlap(
    parameters: list[Parameter],
    correlations: list[CorrelationRule],
) -> tuple[list[Parameter], int]:
    # Pre-build sets for efficient O(1) lookups
    correlated_values = {rule.value for rule in correlations if rule.value}
    correlated_names = {rule.variable for rule in correlations}
    
    kept: list[Parameter] = []
    removed = 0
    
    for parameter in parameters:
        if parameter.value not in correlated_values and parameter.name not in correlated_names:
            kept.append(parameter)
        else:
            removed += 1
    
    return kept, removed
