"""
Value Origin Classifier - Determines whether a value should be classified as correlation or parameter.

This module provides the intelligence to distinguish:
- CORRELATION: Server-generated values (appear in responses, used in later requests)
- PARAMETER: User inputs (appear in requests, vary across test runs)

Example:
  product_id: 12345 (from response body) → CORRELATION
  product_name: "laptop" (in query string) → PARAMETER
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any

from app.models import SamplerModel
from app.patterns import ID_FIELD_RE, GUID_RE, TOKEN_NAME_RE, TOKEN_VALUE_RE


class ValueOrigin(Enum):
    """Where a value originates."""
    RESPONSE_BODY = "response_body"          # In response body
    RESPONSE_HEADER = "response_header"      # In response header
    REQUEST_QUERY = "request_query"          # In request query string
    REQUEST_BODY = "request_body"            # In request POST/PUT body
    REQUEST_HEADER = "request_header"        # In request header
    REQUEST_COOKIE = "request_cookie"        # In request cookie
    UNKNOWN = "unknown"


class ValueClassification(Enum):
    """How a value should be treated."""
    CORRELATION = "correlation"    # Server generates it, used in later requests
    PARAMETER = "parameter"         # User provides it, varies across runs
    METADATA = "metadata"           # Server info (timestamps, status), not parameterized
    HEADER_AUTH = "header_auth"     # Authentication headers, special handling
    EXCLUDE = "exclude"             # Should be ignored (tokens, GUIDs, etc.)


@dataclass
class ValueOriginInfo:
    """Complete information about a value's origin and classification."""
    value: str
    name: str  # Field name
    origin: ValueOrigin
    classification: ValueClassification
    confidence: float  # 0.0-1.0
    reasoning: str
    sampler_names: frozenset[str]  # Where it appears
    request_indices: frozenset[int]  # Request positions
    response_indices: frozenset[int]  # Response positions
    is_reused: bool  # Appears multiple times


class ValueOriginClassifier:
    """
    Analyzes all samplers to classify values as correlations vs parameters.
    
    Algorithm:
    1. Scan all requests and responses
    2. Track where each unique value appears
    3. If value appears in response AND later request → CORRELATION
    4. If value appears only in requests → PARAMETER
    5. Assign confidence based on usage patterns
    """
    
    def __init__(self, samplers: list[SamplerModel]):
        self.samplers = samplers
        self.value_map: dict[str, ValueOriginInfo] = {}
        self._analyze()
    
    def _analyze(self) -> None:
        """Build complete value map across all samplers."""
        # Build indices of where each value appears
        value_appearances: dict[str, dict] = {}
        
        for idx, sampler in enumerate(self.samplers):
            # Response values
            self._collect_response_values(idx, sampler, value_appearances)
            
            # Request values
            self._collect_request_values(idx, sampler, value_appearances)
        
        # Classify each value
        for value, appearances in value_appearances.items():
            info = self._classify_value(value, appearances)
            if info:
                self.value_map[value] = info
    
    def _collect_response_values(
        self,
        idx: int,
        sampler: SamplerModel,
        value_appearances: dict[str, dict],
    ) -> None:
        """Extract values from response body and headers."""
        # Response body JSON
        if sampler.response_text:
            try:
                data = json.loads(sampler.response_text)
                self._extract_json_values(data, idx, ValueOrigin.RESPONSE_BODY, value_appearances)
            except (json.JSONDecodeError, ValueError):
                pass
        
        # Response headers (Set-Cookie, Location, etc.)
        for header_name, header_value in sampler.response_headers:
            if header_name.lower() in {"set-cookie", "location", "content-location"}:
                self._add_value_appearance(
                    header_value, header_name, idx, ValueOrigin.RESPONSE_HEADER, value_appearances
                )
    
    def _collect_request_values(
        self,
        idx: int,
        sampler: SamplerModel,
        value_appearances: dict[str, dict],
    ) -> None:
        """Extract values from request query, body, headers, cookies."""
        # Query parameters
        for param_name, param_value in sampler.query:
            self._add_value_appearance(
                param_value, param_name, idx, ValueOrigin.REQUEST_QUERY, value_appearances
            )
        
        # POST/PUT body
        if sampler.post_body:
            try:
                data = json.loads(sampler.post_body)
                self._extract_json_values(data, idx, ValueOrigin.REQUEST_BODY, value_appearances)
            except (json.JSONDecodeError, ValueError):
                for param_name, param_value in sampler.post_params:
                    self._add_value_appearance(
                        param_value, param_name, idx, ValueOrigin.REQUEST_BODY, value_appearances
                    )
        
        # Headers
        for header_name, header_value in sampler.headers:
            origin = ValueOrigin.REQUEST_HEADER
            if "auth" in header_name.lower():
                origin = ValueOrigin.REQUEST_HEADER
            self._add_value_appearance(header_value, header_name, idx, origin, value_appearances)
        
        # Cookies
        for cookie_name, cookie_value in sampler.cookies:
            self._add_value_appearance(
                cookie_value, cookie_name, idx, ValueOrigin.REQUEST_COOKIE, value_appearances
            )
    
    def _extract_json_values(
        self,
        obj: Any,
        idx: int,
        origin: ValueOrigin,
        value_appearances: dict[str, dict],
        ancestry: list[str] = None,
    ) -> None:
        """Recursively extract values from JSON structure."""
        if ancestry is None:
            ancestry = []
        
        if isinstance(obj, dict):
            for k, v in obj.items():
                current_path = ancestry + [k]
                full_key = ".".join(current_path)
                
                if isinstance(v, str):
                    self._add_value_appearance(v, full_key, idx, origin, value_appearances)
                elif isinstance(v, (int, float)) and not isinstance(v, bool):
                    self._add_value_appearance(str(v), full_key, idx, origin, value_appearances)
                elif isinstance(v, (dict, list)):
                    self._extract_json_values(v, idx, origin, value_appearances, current_path)
        
        elif isinstance(obj, list):
            for item in obj[:10]:  # Limit recursion
                self._extract_json_values(item, idx, origin, value_appearances, ancestry)
    
    def _add_value_appearance(
        self,
        value: str,
        field_name: str,
        idx: int,
        origin: ValueOrigin,
        value_appearances: dict[str, dict],
    ) -> None:
        """Record where a value appears."""
        if not value or len(value) > 500:
            return
        
        value_str = str(value).strip()
        if not value_str or value_str in {"true", "false", "null", "undefined", "none"}:
            return
        
        if value_str not in value_appearances:
            value_appearances[value_str] = {
                "field_names": set(),
                "origins": set(),
                "sampler_indices": set(),
                "response_indices": set(),
                "request_indices": set(),
            }
        
        meta = value_appearances[value_str]
        meta["field_names"].add(field_name)
        meta["origins"].add(origin)
        meta["sampler_indices"].add(idx)
        
        if origin in {ValueOrigin.RESPONSE_BODY, ValueOrigin.RESPONSE_HEADER}:
            meta["response_indices"].add(idx)
        else:
            meta["request_indices"].add(idx)
    
    def _classify_value(self, value: str, appearances: dict) -> ValueOriginInfo | None:
        """Determine if value should be correlation, parameter, or excluded."""
        # Get primary field name (pick the most common one)
        field_names = list(appearances["field_names"])
        primary_field = field_names[0] if field_names else "unknown"
        
        origins = appearances["origins"]
        response_indices = appearances["response_indices"]
        request_indices = appearances["request_indices"]
        sampler_indices = appearances["sampler_indices"]
        
        # Skip obviously non-business values
        if self._should_exclude(value, primary_field):
            return ValueOriginInfo(
                value=value,
                name=primary_field,
                origin=ValueOrigin.UNKNOWN,
                classification=ValueClassification.EXCLUDE,
                confidence=1.0,
                reasoning="Token, GUID, or JWT - not business data",
                sampler_names=frozenset(self.samplers[i].name for i in sampler_indices),
                request_indices=frozenset(request_indices),
                response_indices=frozenset(response_indices),
                is_reused=len(sampler_indices) > 1,
            )
        
        # CORRELATION: Appears in response, then in later requests
        if response_indices and request_indices:
            # Check if responses come before requests (time-based correlation)
            earliest_response = min(response_indices)
            earliest_request = min(request_indices)
            
            if earliest_response < earliest_request:
                confidence = self._calculate_correlation_confidence(
                    value, primary_field, len(request_indices), len(sampler_indices)
                )
                return ValueOriginInfo(
                    value=value,
                    name=primary_field,
                    origin=ValueOrigin.RESPONSE_BODY if ValueOrigin.RESPONSE_BODY in origins else ValueOrigin.RESPONSE_HEADER,
                    classification=ValueClassification.CORRELATION,
                    confidence=confidence,
                    reasoning=f"Server generates (response #{earliest_response+1}) → used in {len(request_indices)} requests",
                    sampler_names=frozenset(self.samplers[i].name for i in sampler_indices),
                    request_indices=frozenset(request_indices),
                    response_indices=frozenset(response_indices),
                    is_reused=True,
                )
        
        # PARAMETER: Only in requests (or only in responses but looks like user input)
        if request_indices or (response_indices and self._looks_like_user_input(value, primary_field)):
            confidence = self._calculate_parameter_confidence(
                value, primary_field, len(sampler_indices)
            )
            return ValueOriginInfo(
                value=value,
                name=primary_field,
                origin=ValueOrigin.REQUEST_QUERY if ValueOrigin.REQUEST_QUERY in origins else ValueOrigin.REQUEST_BODY,
                classification=ValueClassification.PARAMETER,
                confidence=confidence,
                reasoning=f"User input - varies across requests",
                sampler_names=frozenset(self.samplers[i].name for i in sampler_indices),
                request_indices=frozenset(request_indices),
                response_indices=frozenset(response_indices),
                is_reused=len(sampler_indices) > 1,
            )
        
        # METADATA: Only in responses, looks like server info
        if response_indices:
            return ValueOriginInfo(
                value=value,
                name=primary_field,
                origin=ValueOrigin.RESPONSE_BODY,
                classification=ValueClassification.METADATA,
                confidence=0.8,
                reasoning="Server-generated metadata, not reused",
                sampler_names=frozenset(self.samplers[i].name for i in sampler_indices),
                request_indices=frozenset(request_indices),
                response_indices=frozenset(response_indices),
                is_reused=False,
            )
        
        return None
    
    def _should_exclude(self, value: str, field_name: str) -> bool:
        """Check if value should be excluded from analysis."""
        # GUIDs
        if GUID_RE.search(value):
            return True
        
        # JWT-like tokens
        if re.match(r"^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$", value):
            return True
        
        # Long token-like values
        if TOKEN_VALUE_RE.match(value) and len(value) >= 20:
            return True
        
        # Single character
        if len(value) < 1:
            return True
        
        return False
    
    def _looks_like_user_input(self, value: str, field_name: str) -> bool:
        """Check if value looks like something a user would input."""
        # Common business keywords suggesting user input
        user_keywords = {
            "search", "query", "keyword", "filter", "name", "title",
            "description", "category", "status", "email", "phone",
            "username", "password", "page", "size", "limit"
        }
        
        field_lower = field_name.lower()
        return any(kw in field_lower for kw in user_keywords)
    
    def _calculate_correlation_confidence(
        self,
        value: str,
        field_name: str,
        reuse_count: int,
        sampler_count: int,
    ) -> float:
        """Calculate confidence for correlation classification."""
        confidence = 0.5
        
        # Strong indicators
        if ID_FIELD_RE.search(field_name):
            confidence = 0.95
        elif "id" in field_name.lower() or "uuid" in field_name.lower():
            confidence = 0.9
        
        # Reuse boosts confidence
        if reuse_count >= 3:
            confidence = min(0.99, confidence + 0.2)
        elif reuse_count >= 2:
            confidence = min(0.95, confidence + 0.1)
        
        # Numeric IDs are very likely correlations
        if value.isdigit() and 3 <= len(value) <= 10:
            confidence = min(0.99, confidence + 0.15)
        
        return min(1.0, max(0.5, confidence))
    
    def _calculate_parameter_confidence(
        self,
        value: str,
        field_name: str,
        sampler_count: int,
    ) -> float:
        """Calculate confidence for parameter classification."""
        confidence = 0.5
        
        # Business keywords boost confidence
        business_keywords = {
            "search", "query", "keyword", "name", "title",
            "filter", "category", "email", "phone", "username"
        }
        field_lower = field_name.lower()
        
        if any(kw in field_lower for kw in business_keywords):
            confidence = 0.85
        
        # Appearance across multiple requests
        if sampler_count >= 3:
            confidence = min(0.95, confidence + 0.1)
        elif sampler_count >= 2:
            confidence = min(0.9, confidence + 0.05)
        
        # Text values are more likely parameters than pure IDs
        if not value.isdigit():
            confidence = min(0.95, confidence + 0.1)
        
        return min(1.0, max(0.5, confidence))
    
    def classify(self, value: str) -> ValueClassification:
        """Get classification for a specific value."""
        if value in self.value_map:
            return self.value_map[value].classification
        return ValueClassification.EXCLUDE
    
    def get_info(self, value: str) -> ValueOriginInfo | None:
        """Get complete information about a value."""
        return self.value_map.get(value)
    
    def get_correlations(self) -> list[ValueOriginInfo]:
        """Get all values classified as correlations."""
        return [info for info in self.value_map.values()
                if info.classification == ValueClassification.CORRELATION]
    
    def get_parameters(self) -> list[ValueOriginInfo]:
        """Get all values classified as parameters."""
        return [info for info in self.value_map.values()
                if info.classification == ValueClassification.PARAMETER]
