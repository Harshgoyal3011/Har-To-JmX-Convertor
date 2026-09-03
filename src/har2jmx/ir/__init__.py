"""Normalized Intermediate Representation — the spine every reasoning stage reads and annotates.

Public API:
  - NormalizedCapture / NormalizedRequest / Body — the IR dataclasses (``ir.normalized``)
  - build_capture(har) — HAR bytes → NormalizedCapture (``ir.build``)
"""

from __future__ import annotations

from har2jmx.ir.build import build_capture
from har2jmx.ir.normalized import Body, NormalizedCapture, NormalizedRequest

__all__ = [
    "Body",
    "NormalizedCapture",
    "NormalizedRequest",
    "build_capture",
]
