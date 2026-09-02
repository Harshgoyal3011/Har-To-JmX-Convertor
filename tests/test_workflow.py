"""Milestone 4 tests — workflow / transaction discovery.

Runs under pytest, and also directly:  PYTHONPATH=src python tests/test_workflow.py
"""
from __future__ import annotations

from pathlib import Path

from har2jmx.classify import classify_capture
from har2jmx.ir.build import build_capture
from har2jmx.workflow import discover_transactions

FIX = Path(__file__).parent / "fixtures"


def _txns(name: str):
    cap = build_capture((FIX / name).read_bytes())
    classify_capture(cap)
    return cap, discover_transactions(cap)


def test_journey_groups_into_user_actions():
    cap, txns = _txns("sample_flow.har")
    names = [t.name for t in txns]
    assert names == ["Login", "Customer Search", "Open Customer", "Create Order", "Logout"]
    # 10 requests collapse into 5 user actions — NOT one transaction per API.
    assert len(txns) == 5
    assert len(txns) < cap.count


def test_supporting_calls_nest_under_parent():
    _, txns = _txns("sample_flow.har")
    by_name = {t.name: t for t in txns}
    assert by_name["Login"].request_indices == [0, 1, 2]          # html + login + profile support
    assert by_name["Login"].anchor_index == 1                     # anchored on the login POST
    assert by_name["Customer Search"].request_indices == [3, 4]   # search + facets support
    assert by_name["Open Customer"].request_indices == [5, 6]     # open + orders support
    assert by_name["Create Order"].request_indices == [7, 8]      # create + read-back support
    assert by_name["Create Order"].anchor_index == 7


def test_categories():
    _, txns = _txns("sample_flow.har")
    cat = {t.name: t.category for t in txns}
    assert cat["Login"] == "Authentication"
    assert cat["Create Order"] == "Business Action"
    assert cat["Customer Search"] == "Business View"


def test_requests_annotated_with_transaction():
    cap, _ = _txns("sample_flow.har")
    assert cap.requests[1].context.transaction == "Login"
    assert cap.requests[7].context.transaction == "Create Order"
    assert all(r.context.transaction for r in cap.requests)


def test_excluded_requests_nest_not_own_transaction():
    # sample_mini page 2 contains a static SVG and an /eum/ beacon; they must share the
    # surrounding transaction, never spawn one named after a static/beacon.
    cap, txns = _txns("sample_mini.har")
    svg = cap.requests[2]        # logo.svg (excluded static)
    beacon = cap.requests[3]     # /eum/ (excluded telemetry)
    assert svg.context.transaction and beacon.context.transaction
    assert svg.context.transaction == beacon.context.transaction == cap.requests[1].context.transaction
    assert not any("Svg" in t.name or "Eum" in t.name or "Beacon" in t.name for t in txns)


def test_names_are_business_readable_no_ids():
    # alphanumeric ids in the path (SKU-88231-ALPHA, ORD-5501-2026) must never leak into names;
    # list vs detail is distinguished; every name reads as a clear business action.
    _, txns = _txns("sample_naming.har")
    names = [t.name for t in txns]
    assert names == ["View Catalog", "Open Product", "Create Cart", "Create Order", "Open Order", "Update Order"]
    for n in names:
        assert "9001" not in n and "5501" not in n and "SKU" not in n


def test_no_pageref_capture_does_not_crash():
    cap, txns = _txns("sample_noise.har")
    assert len(txns) >= 1
    assert all(r.context.transaction for r in cap.requests)


def test_terminal_action_verb_naming():
    # action endpoints must name from the TERMINAL segment, not a mid-path segment
    cap, txns = _txns("sample_complex_names.har")
    names = [t.name for t in txns]
    assert "Checkout" in names           # POST /api/checkout
    assert "Payment" in names            # POST /api/payment
    assert "View Receipt" in names       # GET /api/payment/{id}/receipt  (NOT 'Payment (2)')
    assert "Initiate Transfer" in names  # POST /api/transfers/initiate   (NOT 'Create Initiate')
    assert "Confirm Transfer" in names   # POST /api/transfers/confirm


def test_keepalive_call_never_names_a_transaction():
    # a background /check (session keepalive) fired on every page must NOT anchor the transaction —
    # otherwise every page reads "Create Check", "Create Check (2)", ... The real user action names it.
    cap, txns = _txns("sample_keepalive.har")
    names = [t.name for t in txns]
    assert not any("Check" in n for n in names), names       # no keepalive-named transactions
    assert "Browse Products" in names                        # POST /bycat
    assert "View Cart" in names                              # POST /viewcart
    # and a read verb (POST /view, /viewcart) reads as View, never "Create"
    assert not any(n.startswith("Create View") for n in names)


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
