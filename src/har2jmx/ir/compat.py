"""Lossless adapters between IR and the current SamplerModel surface.

These exist so Phase 1 can introduce IR without forcing every consumer to
migrate at once. Each later refactor should delete one call site of these
helpers after that module reads ScriptIR / RequestIR directly.
"""

from __future__ import annotations

from har2jmx.ir.models import RequestIR, ScriptIR
from har2jmx.models import CorrelationRule, SamplerModel


def request_ir_to_sampler(request: RequestIR) -> SamplerModel:
    return SamplerModel(
        name=request.name,
        method=request.method,
        url=request.url,
        protocol=request.protocol,
        domain=request.domain,
        port=request.port,
        path=request.path,
        query=list(request.query),
        headers=list(request.headers),
        cookies=list(request.cookies),
        response_headers=list(request.response_headers),
        post_params=list(request.post_params),
        post_body=request.post_body,
        mime_type=request.mime_type,
        transaction=request.transaction,
        status=request.status,
        time_ms=request.time_ms,
        response_text=request.response_text,
        correlations=[],
    )


def sampler_to_request_ir(sampler: SamplerModel, *, index: int = -1, pageref: str = "") -> RequestIR:
    return RequestIR(
        name=sampler.name,
        method=sampler.method,
        url=sampler.url,
        protocol=sampler.protocol,
        domain=sampler.domain,
        port=sampler.port,
        path=sampler.path,
        query=list(sampler.query),
        headers=list(sampler.headers),
        cookies=list(sampler.cookies),
        response_headers=list(sampler.response_headers),
        post_params=list(sampler.post_params),
        post_body=sampler.post_body,
        mime_type=sampler.mime_type,
        transaction=sampler.transaction,
        status=sampler.status,
        time_ms=sampler.time_ms,
        response_text=sampler.response_text,
        correlation_ids=[c.variable for c in sampler.correlations],
        index=index,
        pageref=pageref,
    )


def script_ir_to_samplers(script: ScriptIR) -> list[SamplerModel]:
    return [request_ir_to_sampler(request) for request in script.requests]


def attach_correlations_to_samplers(
    samplers: list[SamplerModel],
    correlations: list[CorrelationRule],
) -> None:
    """Preserve today's attachment semantics (by source_sampler name)."""
    for sampler in samplers:
        sampler.correlations = [r for r in correlations if r.source_sampler == sampler.name]
