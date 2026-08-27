"""
Enhanced parameter discovery with improved business input recognition.
"""
from __future__ import annotations

import json
import re
from typing import Any

from app.models import Parameter, SamplerModel
from app.patterns import (
    EMAIL_VALUE_RE,
    PHONE_VALUE_RE,
    GUID_RE,
    TOKEN_NAME_RE,
    TOKEN_VALUE_RE,
    USER_DATA_RE,
    ENTERPRISE_APP_RULES,
)
from app.utils import variable_name


def discover_parameters_enhanced(samplers: list[SamplerModel]) -> list[Parameter]:
    """
    Enhanced parameter discovery with:
    - Broader business input recognition
    - Scanning from multiple sources
    - Lower thresholds for business data
    - Better pattern matching
    """
    candidates: dict[str, dict] = {}
    
    for sampler in samplers:
        # POST/PUT body parameters
        if sampler.method in {"POST", "PUT", "PATCH"}:
            # Form body parameters
            for name, value in sampler.post_params:
                _consider_param_enhanced(name, value, "form_body", sampler.name, candidates)
            
            # JSON body parameters
            if sampler.post_body:
                try:
                    body_obj = json.loads(sampler.post_body)
                    _scan_json_params(body_obj, sampler.name, "json_body", candidates)
                except (json.JSONDecodeError, ValueError):
                    pass
        
        # Query string parameters
        for name, value in sampler.query:
            _consider_param_enhanced(name, value, "query_string", sampler.name, candidates)
        
        # Request headers (for auth data, etc.)
        for name, value in sampler.headers:
            if _is_auth_related(name):
                _consider_param_enhanced(name, value, "header", sampler.name, candidates)
        
        # Request cookies (business-related only)
        for name, value in sampler.cookies:
            if USER_DATA_RE.search(name) and not TOKEN_NAME_RE.search(name):
                _consider_param_enhanced(name, value, "cookie", sampler.name, candidates)
    
    # Build parameters
    parameters: list[Parameter] = []
    for var_name, meta in candidates.items():
        parameters.append(Parameter(
            name=var_name,
            value=meta["value"],
            occurrences=meta["occurrences"],
            reason=meta["reason"],
            confidence=meta["confidence"],
            csv_bound=True,
            source_samplers=frozenset(meta["samplers"]),
        ))
    
    return sorted(parameters, key=lambda p: (-p.occurrences, p.name))


def _scan_json_params(obj: Any, sampler_name: str, location: str, candidates: dict, ancestry: list[str] = None) -> None:
    """Recursively scan JSON for business parameters."""
    if ancestry is None:
        ancestry = []
    
    if isinstance(obj, dict):
        for k, v in obj.items():
            current_path = ancestry + [k]
            full_key = ".".join(current_path)
            
            if isinstance(v, str):
                _consider_param_enhanced(k, v, location, sampler_name, candidates, full_key)
            elif isinstance(v, (int, float)) and not isinstance(v, bool):
                _consider_param_enhanced(k, str(v), location, sampler_name, candidates, full_key)
            elif isinstance(v, (dict, list)):
                _scan_json_params(v, sampler_name, location, candidates, current_path)
    
    elif isinstance(obj, list):
        for item in obj[:10]:  # Limit recursion
            _scan_json_params(item, sampler_name, location, candidates, ancestry)


def _consider_param_enhanced(
    name: str,
    value: str,
    location: str,
    sampler_name: str,
    candidates: dict,
    full_key: str = "",
) -> None:
    """
    Enhanced parameter consideration with:
    - Lower length thresholds
    - Better business data detection
    - Multi-source support
    """
    if not name or not value:
        return
    
    value_str = str(value).strip()
    
    # Skip obviously non-business values
    if not value_str or len(value_str) > 500:
        return
    
    # Skip tokens, GUIDs, JWTs
    if GUID_RE.search(value_str):
        return
    if TOKEN_VALUE_RE.match(value_str) and len(value_str) >= 20:
        return
    if re.match(r"^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$", value_str):  # JWT pattern
        return
    
    # Skip boolean/null-like values
    if value_str.lower() in {"true", "false", "null", "undefined", "none"}:
        return
    
    # Enhanced business data detection
    is_business = False
    confidence = "Low"
    
    # Email addresses
    if EMAIL_VALUE_RE.match(value_str):
        is_business = True
        confidence = "High"
    
    # Phone numbers
    elif PHONE_VALUE_RE.match(value_str):
        is_business = True
        confidence = "High"
    
    # User data pattern matching
    elif USER_DATA_RE.search(name):
        is_business = True
        confidence = "High"
        
        # Special high-confidence cases
        if any(kw in name.lower() for kw in {"email", "phone", "password", "username"}):
            confidence = "High"
    
    # Query/form parameters that look intentional (not single char, not pure numbers)
    elif len(value_str) >= 2 and not value_str.isdigit():
        # Accept if name looks business-related or location suggests it
        if USER_DATA_RE.search(name) or _looks_like_business_param(name):
            is_business = True
            confidence = "Medium"
    
    # ID-like numeric values
    elif len(value_str) >= 1 and value_str.isdigit() and int(value_str) > 0:
        if _looks_like_id_param(name):
            is_business = True
            confidence = "Medium"
    
    if not is_business:
        return
    
    # Skip if looks like a token/auth field
    if TOKEN_NAME_RE.search(name):
        return
    
    var_name = variable_name(name)
    key_display = full_key or name
    
    if var_name not in candidates:
        candidates[var_name] = {
            "value": value_str,
            "occurrences": 0,
            "samplers": set(),
            "locations": set(),
            "confidence": confidence,
            "reason": f"Business input detected from {location}",
        }
    
    candidates[var_name]["occurrences"] += 1
    candidates[var_name]["samplers"].add(sampler_name)
    candidates[var_name]["locations"].add(location)
    
    # Update reason
    if candidates[var_name]["occurrences"] > 1:
        loc_list = sorted(candidates[var_name]["locations"])
        candidates[var_name]["reason"] = f"Business parameter used in {candidates[var_name]['occurrences']} requests ({', '.join(loc_list)})"


def _looks_like_business_param(name: str) -> bool:
    """Check if parameter name looks business-related."""
    business_keywords = {
        "search", "query", "keyword", "term", "filter",
        "name", "title", "description", "value",
        "type", "category", "status", "state",
        "from", "to", "start", "end", "date",
        "page", "size", "limit", "offset",
        "sort", "order", "direction",
    }
    
    name_lower = name.lower()
    return any(kw in name_lower for kw in business_keywords)


def _looks_like_id_param(name: str) -> bool:
    """Check if parameter name looks like an ID."""
    id_keywords = {"id", "id_", "_id", "uuid", "guid", "code", "number", "ref", "reference"}
    name_lower = name.lower()
    return any(name_lower.endswith(kw) or name_lower.startswith(kw) for kw in id_keywords)


def _is_auth_related(header_name: str) -> bool:
    """Check if header is auth-related (might contain user data)."""
    return any(kw in header_name.lower() for kw in {"authorization", "x-auth", "x-api", "token"})
