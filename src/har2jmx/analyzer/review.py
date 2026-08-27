from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from har2jmx.analyzer.dependency_graph import DependencyGraph
from har2jmx.models import CorrelationRule, Parameter, SamplerModel


@dataclass
class AIReviewFinding:
    """A recommendation or observation from AI review."""
    category: str  # "optimization", "risk", "improvement", "warning"
    severity: str  # "Critical", "High", "Medium", "Low"
    message: str
    affected_items: list[str]  # Correlation/Parameter/Sampler names


@dataclass
class AIReviewResult:
    """Complete AI review analysis."""
    findings: list[AIReviewFinding]
    optimization_score: float  # 0-100
    quality_metrics: dict[str, float]
    recommendations: list[str]


class AIReviewLayer:
    """Intelligent analysis and optimization recommendations layer."""
    
    def review(
        self,
        samplers: list[SamplerModel],
        correlations: list[CorrelationRule],
        parameters: list[Parameter],
        dependency_graph: DependencyGraph,
    ) -> AIReviewResult:
        """Perform comprehensive AI review of the test script."""
        findings: list[AIReviewFinding] = []
        
        # Review 1: Correlation quality
        findings.extend(self._review_correlations(correlations, samplers))
        
        # Review 2: Parameter distribution
        findings.extend(self._review_parameters(parameters, correlations))
        
        # Review 3: Dependency complexity
        findings.extend(self._review_dependencies(dependency_graph))
        
        # Review 4: Sampler characteristics
        findings.extend(self._review_samplers(samplers))
        
        # Calculate metrics
        quality_metrics = self._calculate_metrics(
            samplers, correlations, parameters, dependency_graph
        )
        
        # Generate recommendations
        recommendations = self._generate_recommendations(findings, quality_metrics)
        
        # Calculate optimization score
        optimization_score = self._calculate_optimization_score(quality_metrics)
        
        return AIReviewResult(
            findings=findings,
            optimization_score=optimization_score,
            quality_metrics=quality_metrics,
            recommendations=recommendations,
        )
    
    def _review_correlations(
        self, correlations: list[CorrelationRule], samplers: list[SamplerModel]
    ) -> list[AIReviewFinding]:
        """Review correlation rules for quality and coverage."""
        findings: list[AIReviewFinding] = []
        
        # Check for low-confidence correlations
        low_confidence = [c for c in correlations if c.confidence == "Low"]
        if low_confidence:
            findings.append(AIReviewFinding(
                category="warning",
                severity="Medium",
                message=f"Found {len(low_confidence)} low-confidence correlation(s)",
                affected_items=[c.variable for c in low_confidence],
            ))
        
        # Check for unused correlations (no consumers)
        unused = [c for c in correlations if not c.consumers]
        if unused:
            findings.append(AIReviewFinding(
                category="optimization",
                severity="Low",
                message=f"Found {len(unused)} correlation(s) with no consumers",
                affected_items=[c.variable for c in unused],
            ))
        
        # Check for high-cardinality values
        high_cardinality = [
            c for c in correlations
            if len(c.consumers or []) > len(samplers) * 0.5
        ]
        if high_cardinality:
            findings.append(AIReviewFinding(
                category="optimization",
                severity="Low",
                message="Found highly reused values (consider as global constants)",
                affected_items=[c.variable for c in high_cardinality],
            ))
        
        return findings
    
    def _review_parameters(
        self, parameters: list[Parameter], correlations: list[CorrelationRule]
    ) -> list[AIReviewFinding]:
        """Review parameter distribution and coverage."""
        findings: list[AIReviewFinding] = []
        
        # Check for parameters with low occurrence
        rare = [p for p in parameters if p.occurrences < 2]
        if rare:
            findings.append(AIReviewFinding(
                category="optimization",
                severity="Low",
                message=f"Found {len(rare)} parameter(s) with rare occurrence (< 2)",
                affected_items=[p.name for p in rare],
            ))
        
        # Check for parameters not in CSV
        non_csv = [p for p in parameters if not p.csv_bound]
        if non_csv:
            findings.append(AIReviewFinding(
                category="improvement",
                severity="Low",
                message=f"{len(non_csv)} parameter(s) not CSV-bound (may be UDVs)",
                affected_items=[p.name for p in non_csv],
            ))
        
        return findings
    
    def _review_dependencies(self, dependency_graph: DependencyGraph) -> list[AIReviewFinding]:
        """Review request dependencies for bottlenecks and issues."""
        findings: list[AIReviewFinding] = []
        
        # Check for linear dependency chains (could cause slowdown)
        if len(dependency_graph.request_dependencies) > len(dependency_graph.samplers) * 0.7:
            findings.append(AIReviewFinding(
                category="risk",
                severity="Medium",
                message="High dependency density - many sequential requests may limit parallelization",
                affected_items=[],
            ))
        
        # Check for critical path requests
        critical = [
            s.name for s in dependency_graph.samplers
            if dependency_graph.is_critical_path(s.name)
        ]
        if critical:
            findings.append(AIReviewFinding(
                category="optimization",
                severity="Low",
                message=f"{len(critical)} request(s) are on critical path (removing breaks downstream)",
                affected_items=critical,
            ))
        
        return findings
    
    def _review_samplers(self, samplers: list[SamplerModel]) -> list[AIReviewFinding]:
        """Review sampler characteristics for optimization."""
        findings: list[AIReviewFinding] = []
        
        # Check for large response bodies (slow parsing)
        large_responses = [
            s for s in samplers
            if s.response_text and len(s.response_text) > 100_000
        ]
        if large_responses:
            findings.append(AIReviewFinding(
                category="optimization",
                severity="Low",
                message=f"{len(large_responses)} sampler(s) with large response bodies (>100KB)",
                affected_items=[s.name for s in large_responses],
            ))
        
        # Check for slow requests
        slow = [s for s in samplers if s.time_ms > 5000]
        if slow:
            findings.append(AIReviewFinding(
                category="risk",
                severity="Medium",
                message=f"{len(slow)} slow request(s) (>5s) may cause test delays",
                affected_items=[s.name for s in slow],
            ))
        
        return findings
    
    def _calculate_metrics(
        self,
        samplers: list[SamplerModel],
        correlations: list[CorrelationRule],
        parameters: list[Parameter],
        dependency_graph: DependencyGraph,
    ) -> dict[str, float]:
        """Calculate quality metrics."""
        correlation_coverage = len(correlations) / max(len(samplers), 1) if samplers else 0
        parameterization_ratio = len(parameters) / max(len(samplers), 1) if samplers else 0
        avg_correlation_consumers = (
            sum(len(c.consumers or []) for c in correlations) / len(correlations)
            if correlations else 0
        )
        dependency_density = (
            len(dependency_graph.request_dependencies) / max(len(samplers), 1)
            if samplers else 0
        )
        avg_response_time = sum(s.time_ms for s in samplers) / len(samplers) if samplers else 0
        
        return {
            "correlation_coverage": min(correlation_coverage, 1.0),
            "parameterization_ratio": min(parameterization_ratio, 1.0),
            "avg_correlation_consumers": avg_correlation_consumers,
            "dependency_density": min(dependency_density, 1.0),
            "avg_response_time_ms": avg_response_time,
        }
    
    def _generate_recommendations(
        self, findings: list[AIReviewFinding], metrics: dict[str, float]
    ) -> list[str]:
        """Generate actionable recommendations."""
        recommendations = []
        
        critical_findings = [f for f in findings if f.severity == "Critical"]
        if critical_findings:
            recommendations.append(
                f"🔴 Address {len(critical_findings)} critical finding(s) before running tests"
            )
        
        if metrics["correlation_coverage"] < 0.3:
            recommendations.append(
                "Consider capturing more requests to improve correlation coverage"
            )
        
        if metrics["dependency_density"] > 0.7:
            recommendations.append(
                "High dependency density - consider splitting into smaller modules for parallel execution"
            )
        
        if metrics["avg_response_time_ms"] > 3000:
            recommendations.append(
                "Average response time is high - verify server performance or use think time"
            )
        
        if metrics["parameterization_ratio"] < 0.2:
            recommendations.append(
                "Low parameterization ratio - more data variation could improve realism"
            )
        
        return recommendations
    
    def _calculate_optimization_score(self, metrics: dict[str, float]) -> float:
        """Calculate overall optimization score (0-100)."""
        # Weighted scoring
        score = 0.0
        
        # High correlation coverage is good (40 points)
        score += metrics.get("correlation_coverage", 0) * 40
        
        # Good parameterization ratio (30 points)
        score += min(metrics.get("parameterization_ratio", 0), 1.0) * 30
        
        # Low dependency density is good (20 points)
        score += (1.0 - metrics.get("dependency_density", 0)) * 20
        
        # Reasonable response times (10 points)
        avg_time = metrics.get("avg_response_time_ms", 0)
        time_score = max(0, 1.0 - (avg_time / 10000))  # Penalize if >10s
        score += time_score * 10
        
        return min(score, 100.0)
