"""Intermediate Representation package.

Public API (Phase 1):
  - RequestIR / ScriptIR — IR dataclasses
  - build_script_ir(har) — HAR → ScriptIR (owned by har.samplers for now)
  - request_ir_to_sampler / script_ir_to_samplers — temporary adapters
"""

from __future__ import annotations

from app.ir.compat import (
    attach_correlations_to_samplers,
    request_ir_to_sampler,
    sampler_to_request_ir,
    script_ir_to_samplers,
)
from app.ir.models import RequestIR, ScriptIR

__all__ = [
    "RequestIR",
    "ScriptIR",
    "attach_correlations_to_samplers",
    "request_ir_to_sampler",
    "sampler_to_request_ir",
    "script_ir_to_samplers",
]
