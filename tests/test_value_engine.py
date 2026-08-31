"""Milestone 8 tests — value classification engine."""
from __future__ import annotations

from pathlib import Path

from har2jmx.classify import ValueClass, classify_capture, classify_values
from har2jmx.classify.value_engine import Lifecycle
from har2jmx.ir.build import build_capture

FIX = Path(__file__).parent / "fixtures"


def _result(name: str):
    cap = build_capture((FIX / name).read_bytes())
    classify_capture(cap)
    return classify_values(cap)


def test_runtime_token_is_correlation():
    r = _result("sample_lineage.har")
    v = r.by_value("SID-abc123def")
    assert v.classification == ValueClass.RUNTIME_GENERATED
    assert v.lifecycle == Lifecycle.CREATED_THIS_RUN


def test_created_object_id_is_runtime():
    r = _result("sample_flow.har")
    v = r.by_value("ORD1")            # orderId returned by POST /api/orders 201
    assert v.classification == ValueClass.RUNTIME_GENERATED
    assert v.lifecycle == Lifecycle.CREATED_THIS_RUN
    assert v.entity == "Order"


def test_existing_record_id_is_master_data():
    r = _result("sample_flow.har")
    v = r.by_value("1001")           # customer id returned by a GET/list, then reused
    assert v.classification == ValueClass.BUSINESS_MASTER_DATA
    assert v.lifecycle == Lifecycle.EXISTING_BEFORE_RUN
    assert v.entity == "Customer" and v.is_identifier


def test_ambiguous_value_is_unknown_not_wired():
    r = _result("sample_flow.har")
    v = r.by_value("acme")           # ?q=acme search term, no business-name / entity signal
    assert v is not None and v.classification == ValueClass.UNKNOWN
    # UNKNOWN must never silently become a correlation or a parameter
    assert v not in r.correlations()
    assert v not in r.parameters()


def test_echoed_user_input_is_master_data_not_runtime():
    # customerName is sent by the client, echoed in the create response, then reused in a PUT.
    # It must stay BUSINESS_MASTER_DATA — not become a runtime correlation just because the server
    # echoed it. Only the server-generated orderId is runtime.
    r = _result("sample_echo.har")
    name = r.by_value("Sally")
    assert name.classification == ValueClass.BUSINESS_MASTER_DATA
    assert name.lifecycle == Lifecycle.USER_INPUT
    oid = r.by_value("NEW1")
    assert oid.classification == ValueClass.RUNTIME_GENERATED


def test_user_scoped_id_is_correlated_shared_catalog_id_is_parameterized():
    # A server-returned id read from a PER-USER list (its producer path carries the session uid) must
    # be CORRELATED — a static CSV id belongs to one login and 404s for every other user. A shared
    # catalog id (producer path has no session value) stays master data so the CSV can spread load.
    r = _result("sample_user_scoped.har")
    acc = r.by_value("ACC-778812")     # from GET /users/UID-55021/accounts (session-scoped path)
    assert acc.classification == ValueClass.RUNTIME_GENERATED
    assert acc in r.correlations()
    prod = r.by_value("PROD-4400")     # from GET /products (shared catalog, no session in path)
    assert prod.classification == ValueClass.BUSINESS_MASTER_DATA
    assert prod in r.parameters()


def test_opaque_handle_correlates_coded_id_parameterizes_config_stays_static():
    # the three real-world calls this exercises:
    r = _result("sample_realworld.har")
    #  - an opaque, expiring server handle (singleton, not a catalog item) must be CORRELATED
    quote = r.by_value("Qz7Kf39aPd2")
    assert quote.classification == ValueClass.RUNTIME_GENERATED and quote in r.correlations()
    #  - a structured coded catalog id (one of several products) stays business master data
    prod = r.by_value("PROD-4400")
    assert prod.classification == ValueClass.BUSINESS_MASTER_DATA and prod in r.parameters()
    #  - a UI/config enum is left hardcoded — never a parameter and never a correlation
    layout = r.by_value("grid")
    assert layout.classification == ValueClass.STATIC
    assert layout not in r.parameters() and layout not in r.correlations()
    #  - genuine free-text user input still parameterizes
    note = r.by_value("gift wrap please")
    assert note.classification == ValueClass.BUSINESS_MASTER_DATA


def test_uncaptured_token_is_flagged_for_manual_correlation():
    # the flagged token must appear in needs_correlation() so the tool can surface it; a plain
    # ambiguous client value (?q=acme) must NOT (it is genuinely ignorable, not a correlation gap).
    r = _result("sample_uncaptured_token.har")
    flagged = {v.value for v in r.needs_correlation()}
    assert "YWRtaW4xNzgzMzUy" in flagged
    tok = r.by_value("YWRtaW4xNzgzMzUy")
    assert tok.needs_correlation is True
    amb = _result("sample_flow.har").by_value("acme")
    assert amb is not None and amb.needs_correlation is False


def test_uncaptured_token_is_flagged_not_parameterized():
    # a token used in requests whose issuing response was not captured must NOT land in a CSV — a
    # fixed token there makes every virtual user share one stale session. It is flagged for
    # correlation instead. Real credentials (username/password) still parameterize.
    r = _result("sample_uncaptured_token.har")
    tok = r.by_value("YWRtaW4xNzgzMzUy")
    assert tok.classification == ValueClass.UNKNOWN          # flagged, never wired as data
    assert tok not in r.parameters() and tok not in r.correlations()
    # the genuine login inputs are still business data
    assert r.by_value("admin").classification == ValueClass.BUSINESS_MASTER_DATA


def test_every_verdict_has_reason():
    for name in ("sample_lineage.har", "sample_flow.har", "sample_entities.har"):
        for v in _result(name).verdicts:
            assert v.reason and v.confidence in {"High", "Medium", "Low"}


def test_correlations_and_parameters_partition():
    r = _result("sample_flow.har")
    corr_vals = {v.value for v in r.correlations()}
    param_vals = {v.value for v in r.parameters()}
    assert "ORD1" in corr_vals
    assert "1001" in param_vals
    assert corr_vals.isdisjoint(param_vals)   # a value is never both


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
