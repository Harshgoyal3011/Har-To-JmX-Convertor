from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.models import SamplerModel


@dataclass
class ValueFlow:
    """Represents flow of a value from producer to consumers."""
    value: str
    producer_sampler: str
    producer_index: int
    consumer_samplers: list[str] = field(default_factory=list)
    consumer_indices: list[int] = field(default_factory=list)
    is_dynamic: bool = True
    confidence: str = "Medium"


@dataclass
class RequestDependency:
    """Dependency between two requests."""
    source_request_index: int
    source_request_name: str
    target_request_index: int
    target_request_name: str
    values_transferred: list[str] = field(default_factory=list)


class DependencyGraph:
    """Tracks dependencies and value flows between requests."""
    
    def __init__(self, samplers: list[SamplerModel]):
        self.samplers = samplers
        self.value_flows: list[ValueFlow] = []
        self.request_dependencies: list[RequestDependency] = []
        self._adjacency: dict[str, list[str]] = {}  # request_name → [dependent_request_names]
    
    def build_from_correlations(self, correlations: Any) -> None:
        """Build dependency graph from discovered correlations."""
        # Build value flow map
        value_flow_map: dict[str, ValueFlow] = {}
        
        for correlation in correlations:
            value = correlation.value
            producer = correlation.source_sampler
            consumers = list(correlation.consumers or [])
            
            if value not in value_flow_map:
                # Find producer index
                producer_idx = next(
                    (i for i, s in enumerate(self.samplers) if s.name == producer),
                    -1,
                )
                value_flow_map[value] = ValueFlow(
                    value=value,
                    producer_sampler=producer,
                    producer_index=producer_idx,
                    consumer_samplers=consumers,
                    confidence=correlation.confidence,
                )
                
                # Map consumer indices
                consumer_indices = [
                    i for i, s in enumerate(self.samplers) if s.name in consumers
                ]
                value_flow_map[value].consumer_indices = consumer_indices
        
        self.value_flows = list(value_flow_map.values())
        self._build_request_dependencies()
    
    def _build_request_dependencies(self) -> None:
        """Build request dependency list from value flows."""
        dependencies_set: set[tuple[int, int]] = set()
        
        for flow in self.value_flows:
            producer_idx = flow.producer_index
            for consumer_idx in flow.consumer_indices:
                if producer_idx >= 0 and consumer_idx >= 0 and producer_idx < consumer_idx:
                    dependencies_set.add((producer_idx, consumer_idx))
        
        self.request_dependencies = [
            RequestDependency(
                source_request_index=src_idx,
                source_request_name=self.samplers[src_idx].name,
                target_request_index=tgt_idx,
                target_request_name=self.samplers[tgt_idx].name,
                values_transferred=self._get_values_between(src_idx, tgt_idx),
            )
            for src_idx, tgt_idx in sorted(dependencies_set)
        ]
    
    def _get_values_between(self, from_idx: int, to_idx: int) -> list[str]:
        """Get all values flowing from one request to another."""
        return [
            flow.value
            for flow in self.value_flows
            if flow.producer_index == from_idx and to_idx in flow.consumer_indices
        ]
    
    def has_dependency(self, from_request: str, to_request: str) -> bool:
        """Check if to_request depends on from_request."""
        return any(
            dep.source_request_name == from_request and dep.target_request_name == to_request
            for dep in self.request_dependencies
        )
    
    def get_upstream(self, request_name: str) -> list[str]:
        """Get all requests that this request depends on."""
        request_idx = next(
            (i for i, s in enumerate(self.samplers) if s.name == request_name),
            -1,
        )
        if request_idx < 0:
            return []
        
        return [
            dep.source_request_name
            for dep in self.request_dependencies
            if dep.target_request_index == request_idx
        ]
    
    def get_downstream(self, request_name: str) -> list[str]:
        """Get all requests that depend on this request."""
        request_idx = next(
            (i for i, s in enumerate(self.samplers) if s.name == request_name),
            -1,
        )
        if request_idx < 0:
            return []
        
        return [
            dep.target_request_name
            for dep in self.request_dependencies
            if dep.source_request_index == request_idx
        ]
    
    def is_critical_path(self, request_name: str) -> bool:
        """Check if removing this request would break downstream requests."""
        return len(self.get_downstream(request_name)) > 0
    
    def get_execution_order(self) -> list[str]:
        """Get optimal execution order respecting dependencies."""
        # Topological sort
        in_degree = {s.name: 0 for s in self.samplers}
        
        for dep in self.request_dependencies:
            in_degree[dep.target_request_name] += 1
        
        queue = [s.name for s in self.samplers if in_degree[s.name] == 0]
        order = []
        
        while queue:
            current = queue.pop(0)
            order.append(current)
            
            for downstream in self.get_downstream(current):
                in_degree[downstream] -= 1
                if in_degree[downstream] == 0:
                    queue.append(downstream)
        
        return order
