"""Manual-correlation reporting: surface dynamic values the engine could not auto-correlate."""
from __future__ import annotations

from pathlib import Path

from har2jmx.emit import build_jmx_xml, emit_jmx
from har2jmx.engine import analyze
from har2jmx.webreport import build_manual_correlations, build_web_summary

FIX = Path(__file__).parent / "fixtures"


def _r(name: str):
    return analyze((FIX / name).read_bytes())


def test_web_summary_lists_uncorrelated_token_with_context():
    r = _r("sample_uncaptured_token.har")
    items = build_manual_correlations(r)
    assert len(items) == 1
    it = items[0]
    assert it["field"] in {"token", "cookie"}     # the value is sent under both field names
    assert "YWRtaW4" not in it["value"] or "…" in it["value"]     # value is masked, not shown raw
    assert it["usedIn"] and it["suggestion"] and it["reason"]
    # exposed on the web summary the UI renders
    summary = build_web_summary(r, "rid", {})
    assert summary["manualCorrelations"] == items


def test_clean_flow_has_no_manual_items():
    r = _r("sample_flow.har")
    assert build_manual_correlations(r) == []


def test_emit_writes_review_file_only_when_needed(tmp_path=None):
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        out = Path(d)
        # flagged flow → a review file is written and returned
        _, _, reports = emit_jmx(_r("sample_uncaptured_token.har"), out / "flagged", {"threads": "10"})
        assert len(reports) == 1 and reports[0].name.endswith("_manual_review.md")
        body = reports[0].read_text(encoding="utf-8")
        assert "Manual Correlation Needed" in body and "Fix:" in body
        # clean flow → no review file
        _, _, none = emit_jmx(_r("sample_flow.har"), out / "clean", {"threads": "10"})
        assert none == []


def test_jmx_testplan_comment_warns_when_manual_needed():
    flagged = build_jmx_xml(_r("sample_uncaptured_token.har")).decode()
    assert "need MANUAL correlation" in flagged                    # visible on opening in JMeter
    clean = build_jmx_xml(_r("sample_flow.har")).decode()
    assert "need MANUAL correlation" not in clean


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for fn in fns:
        try:
            fn()
        except AssertionError as e:
            print(f"FAIL  {fn.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            print(f"ERROR {fn.__name__}: {type(e).__name__}: {e}")
        else:
            passed += 1
            print(f"ok    {fn.__name__}")
    print(f"\n{passed}/{len(fns)} passed")
    raise SystemExit(0 if passed == len(fns) else 1)
