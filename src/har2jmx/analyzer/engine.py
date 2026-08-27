from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from har2jmx.har import build_script_ir, read_har
from har2jmx.ir.compat import script_ir_to_samplers
from har2jmx.models import SamplerModel
from har2jmx.patterns import BUSINESS_TRANSACTION_RULES, ENTITY_NAME_RULES


@dataclass
class TransactionGroup:
    """Represents a logical business transaction (e.g., Login, Create Policy)."""
    name: str
    samplers: list[SamplerModel]
    pattern: str
    category: str


@dataclass
class ValueIndex:
    """Pre-computed index of all values extracted from responses."""
    value_to_sources: dict[str, list[tuple[str, str, str]]] = field(default_factory=dict)  # value → [(sampler_name, field, source)]
    field_to_values: dict[str, list[str]] = field(default_factory=dict)  # field_name → [values]
    

@dataclass
class EntityDetectionResult:
    """Results from entity clustering and classification."""
    entity_clusters: dict[str, list[str]]  # entity_type → [field_names]
    confidence_map: dict[str, float]  # field_name → confidence


@dataclass
class AnalysisResult:
    """Complete analysis output from the Analyzer Engine."""
    transaction_groups: list[TransactionGroup]
    value_index: ValueIndex
    entity_detection: EntityDetectionResult
    total_requests: int
    filtered_requests: int


class AnalyzerEngine:
    """Performs initial analysis of HAR data to extract structure and patterns."""
    
    def __init__(self):
        # BUSINESS_TRANSACTION_RULES are already compiled patterns (tuples of (pattern, name))
        self._transaction_patterns = BUSINESS_TRANSACTION_RULES
    
    def analyze(self, har_bytes: bytes) -> AnalysisResult:
        """Analyze HAR file and extract transactions, values, and entities."""
        # Phase 1: Parse HAR to IR and Samplers
        har = read_har(har_bytes)
        script_ir = build_script_ir(har)
        samplers = script_ir_to_samplers(script_ir)
        
        if not samplers:
            raise ValueError("No application/API traffic found after filtering static assets")
        
        filtered_count = len(samplers)
        total_count = script_ir.total_har_entries
        
        # Phase 2: Group into transactions
        transaction_groups = self._detect_transactions(samplers)
        
        # Phase 3: Build value index
        value_index = self._build_value_index(samplers)
        
        # Phase 4: Detect entities
        entity_detection = self._detect_entities(samplers, value_index)
        
        return AnalysisResult(
            transaction_groups=transaction_groups,
            value_index=value_index,
            entity_detection=entity_detection,
            total_requests=total_count,
            filtered_requests=filtered_count,
        )
    
    def _detect_transactions(self, samplers: list[SamplerModel]) -> list[TransactionGroup]:
        """Group samplers into logical business transactions."""
        groups: dict[str, TransactionGroup] = {}
        
        for sampler in samplers:
            # Detect transaction type from path
            tx_name = "Default"
            matched_pattern = ""
            
            for pattern, name in self._transaction_patterns:
                if pattern.search(sampler.path):
                    tx_name = name
                    matched_pattern = pattern.pattern
                    break
            
            if tx_name not in groups:
                groups[tx_name] = TransactionGroup(
                    name=tx_name,
                    samplers=[],
                    pattern=matched_pattern,
                    category=self._categorize_transaction(tx_name),
                )
            
            groups[tx_name].samplers.append(sampler)
        
        return list(groups.values())
    
    def _build_value_index(self, samplers: list[SamplerModel]) -> ValueIndex:
        """Build index of all dynamic values from responses."""
        import json
        
        value_index = ValueIndex()
        
        for sampler in samplers:
            # Extract from JSON responses
            if sampler.response_text:
                try:
                    body = json.loads(sampler.response_text)
                    self._index_json_values(body, sampler.name, value_index)
                except (json.JSONDecodeError, ValueError):
                    pass
            
            # Extract from response headers
            for header_name, header_val in sampler.response_headers:
                if header_val and len(header_val) >= 8:
                    key = f"response_header_{header_name}"
                    if header_val not in value_index.value_to_sources:
                        value_index.value_to_sources[header_val] = []
                    value_index.value_to_sources[header_val].append((sampler.name, header_name, "response_header"))
                    
                    if key not in value_index.field_to_values:
                        value_index.field_to_values[key] = []
                    value_index.field_to_values[key].append(header_val)
        
        return value_index
    
    def _index_json_values(self, obj: Any, sampler_name: str, index: ValueIndex, path: str = "") -> None:
        """Recursively index values from JSON objects."""
        if isinstance(obj, dict):
            for k, v in obj.items():
                current_path = f"{path}.{k}" if path else k
                if isinstance(v, str) and len(v) >= 8:
                    if v not in index.value_to_sources:
                        index.value_to_sources[v] = []
                    index.value_to_sources[v].append((sampler_name, k, "json_body"))
                    
                    if k not in index.field_to_values:
                        index.field_to_values[k] = []
                    index.field_to_values[k].append(v)
                elif isinstance(v, (dict, list)):
                    self._index_json_values(v, sampler_name, index, current_path)
        elif isinstance(obj, list):
            for item in obj[:10]:  # Limit to first 10 items
                self._index_json_values(item, sampler_name, index, path)
    
    def _detect_entities(self, samplers: list[SamplerModel], value_index: ValueIndex) -> EntityDetectionResult:
        """Cluster and classify business entities."""
        entity_clusters: dict[str, list[str]] = {}
        confidence_map: dict[str, float] = {}
        
        for field_name in value_index.field_to_values.keys():
            # Match field to entity type
            entity_type = "generic"
            confidence = 0.5
            
            for pattern, entity_name in ENTITY_NAME_RULES:
                if pattern.search(field_name):
                    entity_type = entity_name
                    confidence = 0.9
                    break
            
            if entity_type not in entity_clusters:
                entity_clusters[entity_type] = []
            
            entity_clusters[entity_type].append(field_name)
            confidence_map[field_name] = confidence
        
        return EntityDetectionResult(
            entity_clusters=entity_clusters,
            confidence_map=confidence_map,
        )
    
    def _categorize_transaction(self, tx_name: str) -> str:
        """Categorize transaction as Authentication, Data, Business, or Other."""
        auth_keywords = {"login", "logout", "auth", "token", "sso", "saml"}
        if any(kw in tx_name.lower() for kw in auth_keywords):
            return "Authentication"
        
        data_keywords = {"create", "update", "delete", "submit", "search"}
        if any(kw in tx_name.lower() for kw in data_keywords):
            return "Business Data"
        
        view_keywords = {"view", "list", "open", "dashboard", "home"}
        if any(kw in tx_name.lower() for kw in view_keywords):
            return "Business View"
        
        return "Other"
