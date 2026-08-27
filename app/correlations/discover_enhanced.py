"""
Enhanced correlation discovery with improved value detection and confidence scoring.
"""
from __future__ import annotations

import json
import re
from typing import Any

from app.correlations.discover import (
    _inventory_response,
    _build_reverse_value_index,
    _build_scan_texts,
    _find_consumers,
    classify_identifier,
)
from app.models import CorrelationRule, SamplerModel
from app.patterns import TOKEN_NAME_RE, ID_FIELD_RE, GUID_RE
from app.utils import variable_name


def discover_correlations_enhanced(samplers: list[SamplerModel]) -> list[CorrelationRule]:
    """
    Enhanced correlation discovery with:
    - More aggressive value detection (lower thresholds for IDs)
    - Better numeric ID detection
    - Improved consumer finding
    - Better confidence scoring
    """
    inventory = []
    
    # Phase 1: Extended value inventory
    for idx, sampler in enumerate(samplers):
        inventory.extend(_inventory_response(idx, sampler))
        # Additional inventory pass for numeric IDs and short values
        inventory.extend(_inventory_numeric_ids(idx, sampler))
    
    # Phase 2: Build indices
    reverse_index = _build_reverse_value_index(samplers)
    scan_texts = _build_scan_texts(samplers)
    
    # Phase 3: Dedup by value & find consumers
    rules: list[CorrelationRule] = []
    claimed_values: set[str] = set()
    
    # Pre-built dicts for O(1) access
    sampler_by_name: dict[str, SamplerModel] = {s.name: s for s in samplers}
    correlations_by_sampler: dict[str, list[CorrelationRule]] = {s.name: [] for s in samplers}
    
    for rv in inventory:
        if rv.value in claimed_values:
            continue
        
        consumers = _find_consumers(rv.value, rv.sampler_index, samplers, reverse_index, scan_texts)
        if not consumers:
            continue
        
        claimed_values.add(rv.value)
        classification = classify_identifier(rv)
        
        # Enhanced confidence scoring
        confidence, reason = _calculate_enhanced_confidence(rv, consumers, samplers)
        
        producer_sampler = sampler_by_name.get(rv.sampler_name)
        rule = CorrelationRule(
            variable=variable_name(rv.field_name),
            source_sampler=rv.sampler_name,
            pattern=rv.pattern,
            field="headers" if rv.source in {"set_cookie", "response_header"} else "body",
            value=rv.value,
            confidence=confidence,
            reason=reason,
            extractor=rv.extractor,
            json_key=rv.json_key,
            classification=classification,
            origin=f"{rv.source} on '{rv.sampler_name}'",
            consumers=tuple(consumers),
            sibling_fields=tuple(rv.sibling_fields.items()),
            producer_sampler_path=producer_sampler.path if producer_sampler else "",
            producer_method=producer_sampler.method if producer_sampler else "",
            producer_status=str(producer_sampler.status) if producer_sampler else "",
        )
        rules.append(rule)
        correlations_by_sampler[rv.sampler_name].append(rule)
    
    # Assign to samplers
    for sampler in samplers:
        sampler.correlations = correlations_by_sampler[sampler.name]
    
    return rules


def _inventory_numeric_ids(index: int, sampler: SamplerModel) -> list[Any]:
    """Enhanced inventory for numeric IDs and short but meaningful values."""
    from app.correlations.discover import _ResponseValue
    
    found = []
    
    # Scan JSON for numeric IDs
    if sampler.response_text:
        try:
            body = json.loads(sampler.response_text)
            found.extend(_scan_numeric_ids(body, index, sampler.name, sampler.path))
        except (json.JSONDecodeError, ValueError):
            pass
    
    # Scan query parameters and post params for patterns
    for param_name, param_value in sampler.query + sampler.post_params:
        if _is_meaningful_value(param_name, param_value, min_len=2):
            found.append(_ResponseValue(
                sampler_index=index,
                sampler_name=sampler.name,
                field_name=param_name,
                value=param_value,
                source="request_param",
                extractor="regex",
                pattern=rf"{re.escape(param_name)}=([^&]+)",
                json_key=param_name,
                sibling_fields={},
            ))
    
    return found


def _scan_numeric_ids(obj: Any, sampler_index: int, sampler_name: str, sampler_path: str, ancestry: list[str] = None) -> list[Any]:
    """Recursively scan for numeric IDs that might be correlations."""
    from app.correlations.discover import _ResponseValue
    
    if ancestry is None:
        ancestry = []
    
    found = []
    
    if isinstance(obj, dict):
        for k, v in obj.items():
            current_path = ancestry + [k]
            full_key = ".".join(current_path)
            
            # Numeric IDs
            if isinstance(v, int) and v > 0 and _looks_like_id(k, v):
                found.append(_ResponseValue(
                    sampler_index=sampler_index,
                    sampler_name=sampler_name,
                    field_name=k,
                    value=str(v),
                    source="json_numeric_id",
                    extractor="json",
                    pattern=rf'"{re.escape(k)}"\s*:\s*(\d+)',
                    json_key=full_key,
                    sibling_fields={},
                ))
            
            # Short UUID/code values
            elif isinstance(v, str) and 3 <= len(v) <= 50 and _looks_like_id(k, v):
                found.append(_ResponseValue(
                    sampler_index=sampler_index,
                    sampler_name=sampler_name,
                    field_name=k,
                    value=v,
                    source="json_id_string",
                    extractor="json",
                    pattern=rf'"{re.escape(k)}"\s*:\s*"([^"]+)"',
                    json_key=full_key,
                    sibling_fields={},
                ))
            
            # Recurse
            elif isinstance(v, (dict, list)):
                found.extend(_scan_numeric_ids(v, sampler_index, sampler_name, sampler_path, current_path))
    
    elif isinstance(obj, list):
        for item in obj[:20]:  # Limit recursion
            found.extend(_scan_numeric_ids(item, sampler_index, sampler_name, sampler_path, ancestry))
    
    return found


def _looks_like_id(field_name: str, value: Any) -> bool:
    """Check if field looks like an ID based on name and value."""
    id_keywords = {"id", "uuid", "guid", "code", "ref", "reference", "key", "number", "identifier"}
    field_lower = field_name.lower()
    
    # Matches ID-like field name
    if any(kw in field_lower for kw in id_keywords):
        return True
    
    if ID_FIELD_RE.search(field_name):
        return True
    
    return False


def _is_meaningful_value(name: str, value: str, min_len: int = 4) -> bool:
    """Check if a parameter value looks meaningful (not random noise)."""
    if not value or len(str(value)) < min_len:
        return False
    
    v = str(value).strip()
    
    # Exclude obvious non-values
    if v.lower() in {"true", "false", "null", "none", "undefined", "1", "0"}:
        return False
    
    # Include if looks like ID or business value
    return (
        _looks_like_id(name, value) or
        GUID_RE.search(v) or
        (len(v) >= min_len and not _is_gibberish(v))
    )


def _is_gibberish(value: str) -> bool:
    """Detect if value looks like random noise."""
    # Very long random strings
    if len(value) > 100:
        return True
    
    # Mostly special characters
    special_count = sum(1 for c in value if not c.isalnum() and c != '-' and c != '_')
    if special_count / len(value) > 0.5:
        return True
    
    return False


def _calculate_enhanced_confidence(rv: Any, consumers: list[str], samplers: list[SamplerModel]) -> tuple[str, str]:
    """
    Enhanced confidence scoring considering:
    - Source type
    - Value characteristics
    - Consumer count
    - Field naming patterns
    """
    confidence = "Medium"
    reason = ""
    
    # Strong signals
    if rv.source == "set_cookie":
        confidence = "High"
        reason = f"Cookie '{rv.field_name}' set by server and reused in {len(consumers)} later request(s) - proven value"
    
    elif rv.source == "response_header" and TOKEN_NAME_RE.search(rv.field_name):
        confidence = "High"
        reason = f"Auth/Token header '{rv.field_name}' returned and reused - high confidence"
    
    elif rv.source in {"json_numeric_id", "json_id_string"}:
        confidence = "High" if len(consumers) >= 1 else "Medium"
        reason = f"ID field '{rv.field_name}' returned and reused in {len(consumers)} request(s) - clear correlation"
    
    elif TOKEN_NAME_RE.search(rv.field_name) and len(rv.value) >= 20:
        confidence = "High"
        reason = f"Token/session pattern detected in '{rv.field_name}' and proven reused"
    
    elif GUID_RE.search(rv.value):
        confidence = "High"
        reason = f"GUID/UUID format in '{rv.field_name}' and reused in {len(consumers)} request(s)"
    
    # Moderate confidence
    elif rv.source == "json_body" and ID_FIELD_RE.search(rv.field_name):
        confidence = "High" if len(consumers) >= 1 else "Medium"
        reason = f"ID-type field '{rv.field_name}' from response, reused in {len(consumers)} request(s)"
    
    elif rv.source in {"html_hidden", "html_input"}:
        confidence = "High"
        reason = f"Hidden/Form field '{rv.field_name}' generated by server and reused"
    
    # Fallback
    else:
        confidence = "Medium"
        reason = f"Value from '{rv.field_name}' ({rv.source}) proven in {len(consumers)} later request(s)"
    
    return confidence, reason
