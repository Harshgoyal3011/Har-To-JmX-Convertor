"""Release-gate pytest wrapper over the tagged corpus (REAL public-API vs SYNTHETIC).

Asserts every gate passes on every real and synthetic HAR in the repo, plus the architecture and
determinism gates. Buckets are reported separately; REAL and SYNTHETIC results are never merged.
"""
from __future__ import annotations

import glob
from pathlib import Path

import pytest

from release_gate import (
    determinism_gate,
    evaluate,
    repo_architecture_gates,
    run_release_checklist,
)
from har2jmx.emit import build_jmx_xml
from har2jmx.engine import analyze

ROOT = Path(__file__).parent.parent
_ALL_HARS = sorted(glob.glob(str(ROOT / "examples" / "*.har"))) + \
    sorted(glob.glob(str(ROOT / "tests" / "fixtures" / "*.har")))


def test_architecture_single_pipeline_no_duplicate_engines():
    for gr in repo_architecture_gates():
        assert gr.passed, f"{gr.name}: {gr.detail}"


def test_determinism_on_real_fixture():
    gr = determinism_gate((ROOT / "tests" / "fixtures" / "sample_flow.har").read_bytes())
    assert gr.passed, gr.detail


@pytest.mark.parametrize("har_path", _ALL_HARS, ids=[Path(p).stem for p in _ALL_HARS])
def test_every_repo_har_passes_release_gates(har_path):
    res = analyze(Path(har_path).read_bytes())
    xml = build_jmx_xml(res, {"threads": "10"}).decode()
    failed = [f"{gr.name} -> {gr.detail}" for gr in evaluate(res, xml) if not gr.passed]
    assert not failed, f"{Path(har_path).name}:\n  " + "\n  ".join(failed)


def test_release_checklist_is_ready():
    checklist, buckets = run_release_checklist()
    blockers = [gr.name for gr in checklist if not gr.passed]
    # every bucket fully green, kept separate (never merged)
    assert buckets["REAL-public-API"].total > 0
    for tag, b in buckets.items():
        assert b.passed == b.total, f"{tag} failures: {b.failures[:5]}"
    assert not blockers, f"RELEASE BLOCKED by: {blockers}"
