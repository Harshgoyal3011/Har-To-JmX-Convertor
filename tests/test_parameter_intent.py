"""Parameter-intent engine: PE would-vary-this, lifecycle over field names, slot evidence."""
from __future__ import annotations

import json

from har2jmx.classify import classify_capture
from har2jmx.engine import analyze
from har2jmx.ir.build import build_capture
from har2jmx.parameterize import ParameterAction, ParameterIntent, build_parameterization


def _e(method, url, status=200, resp="{}", body=None, headers=None, ts="2026-01-01T10:00:00.000Z"):
    req_h = [{"name": "Accept", "value": "application/json"}]
    for k, v in (headers or {}).items():
        req_h.append({"name": k, "value": v})
    e = {
        "startedDateTime": ts, "time": 20,
        "request": {"method": method, "url": url, "headers": req_h, "cookies": []},
        "response": {
            "status": status,
            "headers": [{"name": "Content-Type", "value": "application/json"}],
            "content": {"mimeType": "application/json", "text": resp},
        },
    }
    if body is not None:
        e["request"]["postData"] = {"mimeType": "application/json", "text": body}
        e["request"]["headers"].append({"name": "Content-Type", "value": "application/json"})
    return e


def _har(entries):
    return {"log": {"version": "1.2", "entries": entries}}


def _plan(entries):
    cap = build_capture(_har(entries))
    classify_capture(cap)
    return build_parameterization(cap)


def _csv_values(plan):
    return {v for d in plan.datasets for row in d.rows for v in row.values()}


def test_selected_existing_record_is_parameterized_not_correlated_name():
    # GET list returns an existing identity; later request uses it in the path.
    # Same field name as a create-flow would use — lifecycle says PARAMETERIZE.
    plan = _plan([
        _e("GET", "https://svc.example/items",
           resp='{"items":[{"itemId":"ITM-1001","label":"Alpha"}]}'),
        _e("GET", "https://svc.example/items/ITM-1001",
           resp='{"itemId":"ITM-1001"}', ts="2026-01-01T10:00:02.000Z"),
    ])
    assert "ITM-1001" in _csv_values(plan)
    cols = [c for d in plan.datasets for c in d.columns]
    chosen = next(c for c in cols if c.sample == "ITM-1001" or "ITM-1001" in (c.original, c.normalized))
    assert chosen.intent == ParameterIntent.SELECTED_EXISTING_DATA.value
    assert any(s.slot_kind == "path" for s in chosen.slots)
    assert chosen.producer_location.startswith("response.body:")
    assert chosen.producer_index == 0


def test_created_this_run_identity_never_enters_csv():
    plan = _plan([
        _e("POST", "https://svc.example/items", status=201,
           body='{"label":"fresh"}', resp='{"itemId":"ITM-9876"}'),
        _e("GET", "https://svc.example/items/ITM-9876",
           resp='{"itemId":"ITM-9876"}', ts="2026-01-01T10:00:02.000Z"),
    ])
    assert "ITM-9876" not in _csv_values(plan)


def test_same_field_name_select_vs_create_are_opposite_actions():
    select = _plan([
        _e("GET", "https://a.example/policies",
           resp='{"policies":[{"policyNumber":"POL-1001"}]}'),
        _e("GET", "https://a.example/policies/POL-1001", resp="{}", ts="2026-01-01T10:00:03.000Z"),
    ])
    create = _plan([
        _e("POST", "https://a.example/policies", status=201,
           body='{"name":"n"}', resp='{"policyNumber":"POL-9876"}'),
        _e("GET", "https://a.example/policies/POL-9876", resp="{}", ts="2026-01-01T10:00:03.000Z"),
    ])
    assert "POL-1001" in _csv_values(select)
    assert "POL-9876" not in _csv_values(create)


def test_user_input_form_fields_parameterize_with_slots():
    plan = _plan([
        _e("POST", "https://idp.example/login",
           body='{"username":"loaduser01","password":"S3cretPass"}',
           resp='{"ok":true}'),
    ])
    values = _csv_values(plan)
    assert "loaduser01" in values and "S3cretPass" in values
    for col in (c for d in plan.datasets for c in d.columns if c.sample in {"loaduser01", "S3cretPass"}):
        assert col.intent == ParameterIntent.USER_INPUT.value
        assert col.controller == "user"
        assert any(s.slot_kind == "body" for s in col.slots)


def test_telemetry_only_values_are_not_csv_columns():
    plan = _plan([
        _e("POST", "https://www.google-analytics.com/g/collect?tid=G-ABCDEFG123&en=page_view",
           resp="{}", body=""),
        _e("GET", "https://app.example/home", resp='{"ok":true}', ts="2026-01-01T10:00:01.000Z"),
    ])
    assert "G-ABCDEFG123" not in _csv_values(plan)


def test_unknown_client_value_is_review_not_a_column():
    plan = _plan([
        _e("POST", "https://app.example/rpc",
           body='{"nonceBlob":"zz9yy8xx7ww6vv"}', resp='{"ok":true}'),
    ])
    assert "zz9yy8xx7ww6vv" not in _csv_values(plan)
    assert any(it.value == "zz9yy8xx7ww6vv" and it.intent == ParameterIntent.UNKNOWN.value
               for it in plan.review)


def test_intent_engine_does_not_rely_on_domain_field_names():
    # Invented resource names (not patient/policy/order) still follow lifecycle.
    r = analyze(json.dumps(_har([
        _e("GET", "https://n.example/widgets",
           resp='{"widgets":[{"widgetRef":"W-4400"}]}'),
        _e("POST", "https://n.example/widgets/W-4400/activate",
           body='{"widgetRef":"W-4400"}', resp='{"ok":true}', ts="2026-01-01T10:00:04.000Z"),
    ])).encode())
    assert "W-4400" in _csv_values(r.parameterization)
    assert not any(c.value == "W-4400" for c in r.correlations)


def test_parameter_action_partition():
    assert ParameterAction.PARAMETERIZE.value == "PARAMETERIZE"
    assert ParameterIntent.SELECTED_EXISTING_DATA.value == "SELECTED_EXISTING_DATA"
