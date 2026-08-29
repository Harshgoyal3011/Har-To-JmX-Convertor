"""Milestone 9 tests — lifecycle-aware correlation engine."""
from __future__ import annotations

from pathlib import Path

from har2jmx.classify import classify_capture
from har2jmx.correlate import ExtractorType, build_correlations
from har2jmx.ir.build import build_capture

FIX = Path(__file__).parent / "fixtures"


def _corr(name: str):
    cap = build_capture((FIX / name).read_bytes())
    classify_capture(cap)
    decisions = build_correlations(cap)
    return {d.variable: d for d in decisions}, decisions


def test_created_id_gets_json_extractor():
    by_var, _ = _corr("sample_flow.har")
    assert "orderId" in by_var
    d = by_var["orderId"]
    assert d.extractor == ExtractorType.JSON
    assert d.expression in ("$.orderId", "$..orderId")
    assert d.consumers and d.value == "ORD1"


def test_master_data_id_is_not_correlated():
    by_var, _ = _corr("sample_flow.har")
    # customer 1001 is existing master data → must NOT be a correlation
    assert all(d.value != "1001" for d in by_var.values())


def test_session_cookie_uses_cookie_manager():
    by_var, _ = _corr("sample_lineage.har")
    assert "AUTH" in by_var
    assert by_var["AUTH"].extractor == ExtractorType.COOKIE_MANAGER   # replayed via Cookie Manager
    assert by_var["AUTH"].value == "SID-abc123def"


def test_runtime_userid_json_extractor():
    by_var, _ = _corr("sample_lineage.har")
    assert "userId" in by_var and by_var["userId"].extractor == ExtractorType.JSON


def test_bearer_token_in_authorization_header_is_correlated():
    # accessToken issued in the login response body, consumed as "Authorization: Bearer <token>".
    # Whole-slot matching would miss it because of the scheme prefix — the engine must still catch it.
    by_var, _ = _corr("sample_bearer.har")
    assert "accessToken" in by_var
    d = by_var["accessToken"]
    assert d.extractor == ExtractorType.JSON and d.expression in ("$.accessToken", "$..accessToken")
    assert 1 in d.consumers                       # consumed by GET /api/me
    # refreshToken is never reused → must NOT be correlated
    assert "refreshToken" not in by_var


def test_html_csrf_token_correlated():
    # __RequestVerificationToken lives in a hidden HTML input on the login page and is posted back
    # in the form — a server-rendered app (ASP.NET/JSF/Django/Rails). Must be correlated via HTML.
    by_var, _ = _corr("sample_csrf.har")
    assert "RequestVerificationToken" in by_var
    d = by_var["RequestVerificationToken"]
    assert d.extractor == ExtractorType.REGEX
    assert 1 in d.consumers                       # posted back in the login form


def test_short_values_not_correlated():
    # a bare "7" (user id) is too ambiguous to correlate
    by_var, _ = _corr("sample_bearer.har")
    assert all(len(d.value) >= 3 for d in by_var.values())


def test_no_variable_name_collision_across_different_values():
    # two created objects both returning {"id": ...} must NOT share one JMeter variable, or the
    # second extractor clobbers the first and the wrong id is replayed (404 at 100 users).
    by_var, decisions = _corr("sample_dup_id.har")
    names = [d.variable for d in decisions]
    assert len(names) == len(set(names))               # unique names
    assert "orderId" in by_var and by_var["orderId"].value == "ORD-111"
    assert "shipmentId" in by_var and by_var["shipmentId"].value == "SHP-999"


def test_no_extractor_without_consumer_and_no_duplicates():
    _, decisions = _corr("sample_flow.har")
    assert all(d.consumers for d in decisions)                # every extractor has a consumer
    keys = [(d.variable, d.value) for d in decisions]
    assert len(keys) == len(set(keys))                        # no duplicates


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
