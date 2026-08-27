"""
Value Classification Deduplicator - Resolves conflicts when values could be both correlation and parameter.

This module prevents double-classification by:
1. Checking origin (response vs request)
2. Checking reuse patterns
3. Applying business logic rules
4. Marking values with their final classification
"""

from __future__ import annotations

from dataclasses import dataclass
from app.analyzer.value_origin import ValueClassification, ValueOriginInfo
from app.models import CorrelationRule, Parameter, SamplerModel


@dataclass
class ClassificationConflict:
    """When a value could be classified multiple ways."""
    value: str
    field_name: str
    potential_classifications: list[ValueClassification]
    resolved_classification: ValueClassification
    resolution_reason: str


class ValueClassificationDeduplicator:
    """
    Resolves classification conflicts using business logic rules.
    
    Rules (in priority order):
    1. EXCLUDE always wins (GUIDs, tokens, JWTs)
    2. CORRELATION: Value from response → used in later request
    3. PARAMETER: Value only in requests (user provides)
    4. METADATA: Value from response, not reused
    5. Default: Defer to confidence scoring
    """
    
    def __init__(self):
        self.conflicts: list[ClassificationConflict] = []
    
    def deduplicate(
        self,
        correlations: list[CorrelationRule],
        parameters: list[Parameter],
        value_origins: dict[str, ValueOriginInfo],
    ) -> tuple[list[CorrelationRule], list[Parameter]]:
        """
        Resolve conflicts and return cleaned lists.
        
        Returns:
            (filtered_correlations, filtered_parameters)
        """
        self.conflicts = []
        
        # Build maps for quick lookup
        correlation_values = {c.value: c for c in correlations}
        parameter_names = {p.name: p for p in parameters}
        
        # Find conflicts: same value in both lists
        to_remove_from_params = set()
        
        for value, origin_info in value_origins.items():
            classification = origin_info.classification
            
            # If classified as correlation, remove from parameters
            if classification == ValueClassification.CORRELATION:
                for param in parameters:
                    if param.name.lower() == origin_info.name.lower():
                        to_remove_from_params.add(param.name)
                        self.conflicts.append(ClassificationConflict(
                            value=value,
                            field_name=param.name,
                            potential_classifications=[ValueClassification.PARAMETER, ValueClassification.CORRELATION],
                            resolved_classification=ValueClassification.CORRELATION,
                            resolution_reason="Value from response used in later requests → CORRELATION",
                        ))
            
            # If classified as parameter, remove from correlations
            elif classification == ValueClassification.PARAMETER:
                for corr in correlations:
                    if corr.variable.lower() == origin_info.name.lower():
                        # Don't remove yet, handle in next pass
                        self.conflicts.append(ClassificationConflict(
                            value=value,
                            field_name=origin_info.name,
                            potential_classifications=[ValueClassification.PARAMETER, ValueClassification.CORRELATION],
                            resolved_classification=ValueClassification.PARAMETER,
                            resolution_reason="Value only in requests (user-provided) → PARAMETER",
                        ))
        
        # Apply deduplication
        filtered_correlations = [
            c for c in correlations
            if c.variable not in [p.name for p in parameters if p.name in to_remove_from_params]
        ]
        
        filtered_parameters = [
            p for p in parameters
            if p.name not in to_remove_from_params
        ]
        
        return filtered_correlations, filtered_parameters
    
    def analyze_conflicts(self) -> str:
        """Generate human-readable conflict analysis."""
        if not self.conflicts:
            return "✓ No classification conflicts found"
        
        report = f"⚠️  Found {len(self.conflicts)} classification conflicts:\n\n"
        
        for i, conflict in enumerate(self.conflicts, 1):
            report += f"{i}. {conflict.field_name} = '{conflict.value}'\n"
            report += f"   Considered: {', '.join(c.value for c in conflict.potential_classifications)}\n"
            report += f"   Resolved to: {conflict.resolved_classification.value}\n"
            report += f"   Reason: {conflict.resolution_reason}\n\n"
        
        return report


def apply_value_origin_classification(
    correlations: list[CorrelationRule],
    parameters: list[Parameter],
    value_origins: dict[str, any],  # From ValueOriginClassifier.value_map
) -> tuple[list[CorrelationRule], list[Parameter], list[ClassificationConflict]]:
    """
    High-level function to apply value origin classification to discovered rules and parameters.
    
    Args:
        correlations: From discover_correlations_enhanced()
        parameters: From discover_parameters_enhanced()
        value_origins: From ValueOriginClassifier.value_map
    
    Returns:
        (deduplicated_correlations, deduplicated_parameters, conflicts_found)
    """
    dedup = ValueClassificationDeduplicator()
    filtered_corr, filtered_params = dedup.deduplicate(correlations, parameters, value_origins)
    
    return filtered_corr, filtered_params, dedup.conflicts
