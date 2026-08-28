"""Dry-run acceptance: every example/fixture HAR must emit a production-clean JMeter plan.

This is the cross-application gate — if any change makes a generated script ship a literal secret,
reference an undefined variable, drop a constituent, or leave a dead extractor, this fails.
"""
from __future__ import annotations

from pathlib import Path

from har2jmx.emit import build_jmx_xml, validate_plan
from har2jmx.engine import analyze

try:
    import pytest
except ModuleNotFoundError:  # allow running as a plain script without pytest installed
    pytest = None

ROOT = Path(__file__).parent.parent
HARS = sorted((ROOT / "examples").glob("*.har")) + sorted((Path(__file__).parent / "fixtures").glob("sample_*.har"))


def _validate(har: Path) -> list[str]:
    result = analyze(har.read_bytes())
    xml = build_jmx_xml(result, {"threads": "50", "loops": "5", "ramp": "20"})
    return validate_plan(result, xml)


if pytest is not None:
    @pytest.mark.parametrize("har", HARS, ids=[h.stem for h in HARS])
    def test_generated_plan_is_production_clean(har):
        issues = _validate(har)
        assert not issues, f"{har.stem}: " + " | ".join(issues)


if __name__ == "__main__":
    passed = 0
    for har in HARS:
        issues = _validate(har)
        if issues:
            print(f"FAIL  {har.stem}: " + " | ".join(issues))
        else:
            passed += 1
            print(f"ok    {har.stem}")
    print(f"\n{passed}/{len(HARS)} plans production-clean")
    raise SystemExit(0 if passed == len(HARS) else 1)
