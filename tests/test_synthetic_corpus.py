"""Pytest gate over the SYNTHETIC ~100-scenario corpus (tests/corpus_synthetic.py).

Each scenario is analyzed by the real engine and its checks are evaluated against the actual generated
JMX/CSV. These are synthetic HAR patterns, NOT real captured applications.
"""
from __future__ import annotations

import pytest

from corpus_synthetic import SCENARIOS, build_ctx

_SCEN = SCENARIOS()


def test_corpus_has_at_least_100_checks():
    total = sum(len(s.checks) for s in _SCEN)
    assert len(_SCEN) >= 90 and total >= 100, f"{len(_SCEN)} scenarios, {total} checks"


@pytest.mark.parametrize("sc", _SCEN, ids=[s.sid for s in _SCEN])
def test_synthetic_scenario(sc):
    ctx = build_ctx(sc.entries, sc.config)
    failures = []
    for label, fn in sc.checks:
        ok, detail = fn(ctx)
        if not ok:
            failures.append(f"{label} -> {detail}")
    assert not failures, f"{sc.sid} ({sc.archetype}):\n  " + "\n  ".join(failures)
