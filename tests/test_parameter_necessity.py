"""Intent/provenance regressions: CSV minimality with unchanged runtime ownership."""
import json
from urllib.parse import quote
from xml.etree import ElementTree as ET

import pytest

from har2jmx.emit import build_jmx_xml
from har2jmx.engine import analyze
from har2jmx.lineage import build_lineage
from har2jmx.parameterize import ParameterAction
from har2jmx.parameterize.intent import decide_intents


def entry(method, path, body=None, response=None, *, index=0, form=None, headers=None, status=200):
    req = {'method': method, 'url': 'https://unfamiliar.example' + path,
           'headers': [{'name': k, 'value': v} for k, v in (headers or {}).items()]}
    if body is not None:
        req['postData'] = {'mimeType': 'application/json', 'text': json.dumps(body)}
    if form is not None:
        # Chrome HAR params can retain percent-encoded values, unlike parsed raw forms.
        req['postData'] = {'mimeType': 'application/x-www-form-urlencoded',
                           'params': [{'name': k, 'value': v} for k, v in form.items()]}
    return {'startedDateTime': f'2026-01-01T10:00:{index:02}.000Z', 'time': 10,
            'request': req,
            'response': {'status': status, 'headers': [],
                         'content': {'mimeType': 'application/json', 'text': json.dumps(response or {})}}}


def plan(entries):
    r = analyze({'log': {'version': '1.2', 'entries': entries}})
    xml = build_jmx_xml(r).decode()
    return r, xml


def columns(r):
    return {c.name for d in r.parameterization.datasets for c in d.columns}


def values(r):
    return {v for d in r.parameterization.datasets for row in d.rows for v in row.values()}


@pytest.mark.parametrize('field,value', [('username', 'loaduser'), ('password', 'Secret123'),
                                       ('email', 'load@example.test'), ('signInName', 'load@example.test')])
def test_explicit_login_input_even_when_echoed(field, value):
    r, xml = plan([entry('POST', '/login', {field: value}, {field: value})])
    assert field in columns(r)
    assert '${' + field + '}' in xml
    assert value in values(r)
    assert not any(c.value == value for c in r.correlations)


def test_mfa_answer_is_input_challenge_and_token_are_runtime():
    r, xml = plan([
        entry('POST', '/login', {'username': 'loaduser', 'password': 'Secret123'},
              {'challengeId': 'CHALLENGE-9ab1c2d3'}),
        entry('POST', '/mfa/verify', {'challengeId': 'CHALLENGE-9ab1c2d3', 'otp': '123456'},
              {'accessToken': 'abc.def.ghi'}, index=1),
        entry('GET', '/workspace', headers={'Authorization': 'Bearer abc.def.ghi'}, index=2),
    ])
    assert columns(r) == {'username', 'password', 'otp'}
    assert {'CHALLENGE-9ab1c2d3', 'abc.def.ghi'} <= {c.value for c in r.correlations}
    assert '${otp}' in xml


def test_business_inputs_and_controls_with_equal_values_are_separate():
    r, xml = plan([entry('POST', '/orders/create', {
        'searchTerm': 'harbour', 'quantity': 3, 'selectedDate': '2026-04-05',
        'pageSize': 3, 'pageNumber': 1, 'pageNo': 1, 'fixedFlag': True, 'apiVersion': 'v4',
    })])
    assert columns(r) == {'searchTerm', 'quantity', 'selectedDate'}
    assert '"pageSize": 3' in xml and '"pageNumber": 1' in xml
    assert '"quantity": "${quantity}"' in xml


def test_unknown_measurements_in_observation_record_and_mixed_business_payload():
    measurements = {'entryType': 'resource', 'startTime': 1, 'duration': 42,
                    'fetchStart': 2, 'responseStart': 10, 'domComplete': 20,
                    'requestStart': 3, 'navigationId': 88, 'newBrowserMetric': 901}
    r, _ = plan([entry('POST', '/orders/create', {
        'quantity': 2, 'description': 'deliver tomorrow',
        'diagnostics': {'entries': [measurements], 'connection': {'downlink': 4.7}},
    })])
    assert columns(r) == {'quantity', 'description'}
    assert not ({'901', '4.7', '88', '42'} & values(r))


def test_custom_rum_schema_generalizes_without_vendor_or_field_dictionary():
    r, _ = plan([entry('POST', '/ingest', {
        'metrics': {'unit': 'ms', 'samples': [{'xqvPhase': 22, 'unseenCounter': 913}],
                    'timestamp': 1771234567890},
    })])
    assert not columns(r)


def test_diagnostic_event_envelope_excludes_unknown_attributes_and_metadata():
    """Synthetic mechanics regression; real evidence is the new SauceDemo HAR."""
    r, _ = plan([entry('POST', '/submit', {
        'application': 'unfamiliar producer', 'appversion': '8.2',
        'unseen_event_batch': [{'timestamp': 1771234567, 'attributes': {
            'browser.brand': 'Example', 'window.newDimension': '721',
            'device.unseenProperty': 'opaque', 'zxqv': 'never a test input',
        }}], 'metadata': {'discardedEvents': 9},
    })])
    assert not columns(r)


def test_mixed_event_payload_keeps_business_input_outside_observation():
    r, _ = plan([entry('POST', '/orders/submit', {
        'quantity': 7, 'description': 'deliver to reception',
        'records': [{'timestamp': 1771234567, 'attributes': {
            'browser.brand': 'Example', 'window.newDimension': '721',
            'device.unseenProperty': 'opaque', 'zxqv': 'not user input',
        }}],
    })])
    assert columns(r) == {'quantity', 'description'}


def test_timestamp_and_attributes_alone_do_not_exclude_business_event():
    r, _ = plan([entry('POST', '/orders/submit', {
        'timestamp': 1771234567, 'attributes': {'quantity': 7, 'description': 'deliver to reception'},
    })])
    assert {'quantity', 'description'} <= columns(r)


def test_unknown_config_document_is_not_selected_master_data():
    r, _ = plan([
        entry('GET', '/config', response={'settings': {'xqvMode': 'amber'}}),
        entry('POST', '/rpc', {'xqvMode': 'amber'}, index=1),
    ])
    assert not columns(r)


def test_unknown_business_argument_requires_action_context():
    good, _ = plan([entry('POST', '/widgets/create', {'zxqv': 'harbour-port'})])
    unknown, _ = plan([entry('POST', '/rpc', {'zxqv': 'harbour-port'})])
    assert columns(good) == {'zxqv'}
    assert not columns(unknown)
    assert any(r.value == 'harbour-port' for r in unknown.parameterization.review)


def test_same_field_selected_vs_generated_uses_existing_provenance():
    selected, _ = plan([
        entry('GET', '/widgets', response={'widgets': [{'widgetId': 'W-4400'}, {'widgetId': 'W-5500'}]}),
        entry('POST', '/widgets/activate', {'widgetId': 'W-4400'}, index=1),
    ])
    created, _ = plan([
        entry('POST', '/widgets/create', {'name': 'fresh'}, {'widgetId': 'W-9876'}, status=201),
        entry('POST', '/widgets/activate', {'widgetId': 'W-9876'}, index=1),
    ])
    assert 'W-4400' in values(selected) and 'W-5500' not in values(selected)
    assert 'W-9876' not in values(created)
    assert 'W-9876' in {c.value for c in created.correlations}


def test_url_encoded_login_aliases_share_one_logical_column():
    identity = 'perftest@example.test'
    password = 'Secret@123'
    r, xml = plan([
        entry('POST', '/login', form={'signInName': quote(identity), 'password': quote(password)}),
        entry('POST', '/profile', {'userName': identity}, index=1),
        entry('POST', '/login', {'username': identity}, index=2),
    ])
    assert columns(r) == {'signInName', 'password'}
    assert {identity, password} == values(r)
    assert xml.count('${signInName}') >= 3
    assert quote(password) not in xml and password not in xml
    args = ET.fromstring(xml).findall('.//elementProp[@elementType="HTTPArgument"]')
    for arg in args:
        if arg.findtext('stringProp[@name="Argument.name"]') in {'signInName', 'password'}:
            assert arg.findtext('boolProp[@name="HTTPArgument.always_encode"]') == 'true'


def test_qualified_username_form_uses_existing_login_csv_owner(tmp_path):
    import csv
    from har2jmx.emit import emit_jmx
    identity = 'load+user@example.test'
    result, xml = plan([
        entry('POST', '/login', form={'username': quote(identity, safe='')}),
        entry('POST', '/sso/login', form={'pf.username': quote(identity, safe=''), 'pf.pass': 'Secret123'}, index=1),
    ])
    assert columns(result) == {'username', 'pf_pass'}
    column = next(c for d in result.parameterization.datasets for c in d.columns if c.name == 'username')
    assert {(s.request_index, s.location) for s in column.slots} == {
        (0, 'request.body:username'), (1, 'request.body:pf.username')}
    path, csvs, _ = emit_jmx(result, tmp_path, {'threads': '1'})
    args = ET.parse(path).findall('.//elementProp[@elementType="HTTPArgument"]')
    usernames = [a for a in args if a.findtext('stringProp[@name="Argument.name"]') in {'username', 'pf.username'}]
    assert len(usernames) == 2
    assert all(a.findtext('stringProp[@name="Argument.value"]') == '${username}' for a in usernames)
    assert all(a.findtext('boolProp[@name="HTTPArgument.always_encode"]') == 'true' for a in usernames)
    rows = list(csv.DictReader(csvs[0].open(encoding='utf-8', newline='')))
    assert rows[0]['username'] == identity
    assert not result.correlations


def test_qualified_username_with_different_value_keeps_independent_owner():
    result, xml = plan([
        entry('POST', '/login', form={'username': 'first@example.test'}),
        entry('POST', '/sso/login', form={'pf.username': 'second@example.test'}, index=1),
    ])
    assert columns(result) == {'username', 'pf_username'}
    args = ET.fromstring(xml).findall('.//elementProp[@elementType="HTTPArgument"]')
    bound = {a.findtext('stringProp[@name="Argument.name"]'): a.findtext('stringProp[@name="Argument.value"]') for a in args}
    assert bound['username'] == '${username}'
    assert bound['pf.username'] == '${pf_username}'


@pytest.mark.parametrize('field,expected', [('pf.username', 'identity'), ('auth.signInName', 'identity'),
    ('auth.password', 'secret'), ('notusername', ''), ('usernameHinting', ''), ('pf.adapterId', '')])
def test_credential_namespace_requires_exact_known_leaf(field, expected):
    from har2jmx.parameterize.context import credential_kind
    assert credential_kind(field) == expected


def test_equal_unrelated_inputs_are_not_merged():
    r, _ = plan([entry('POST', '/delivery/create', {'origin': 'DEL', 'destination': 'DEL'})])
    assert columns(r) == {'origin', 'destination'}


def test_username_and_password_with_equal_samples_remain_distinct():
    r, xml = plan([entry('POST', '/login', {'username': 'loaduser', 'password': 'loaduser'})])
    assert columns(r) == {'username', 'password'}
    assert '"username": "${username}"' in xml
    assert '"password": "${password}"' in xml


def test_unknown_configuration_subtree_does_not_inherit_action_input_role():
    r, _ = plan([entry('POST', '/widgets/create', {
        'name': 'fresh', 'configuration': {'xqvSetting': 'amber', 'strangeLimit': 987},
    })])
    assert columns(r) == {'name'}


def test_repeated_spelling_different_step_values_do_not_collapse():
    r, xml = plan([
        entry('POST', '/search', {'searchTerm': 'alpha'}),
        entry('POST', '/search', {'searchTerm': 'beta'}, index=1),
        entry('POST', '/rpc', {'searchTerm': 'gamma'}, index=2),
    ])
    assert len(columns(r)) == 3
    assert values(r) == {'alpha', 'beta', 'gamma'}
    assert '${searchTerm_step2}' in xml


def test_parameter_does_not_replace_equal_literal_in_another_request():
    r, xml = plan([
        entry('POST', '/search', {'searchTerm': 'alpha'}),
        entry('POST', '/rpc', {'xqvMode': 'alpha'}, index=1),
    ])
    assert columns(r) == {'searchTerm'}
    assert '"xqvMode": "alpha"' in xml
    assert '"xqvMode": "${searchTerm}"' not in xml


def test_unresolved_runtime_never_falls_back_to_csv():
    r, _ = plan([entry('POST', '/orders/create', {'accessToken': 'opaqueUncaptured1234'})])
    assert not columns(r)
    assert any(v.needs_correlation for v in r.classification.verdicts)


@pytest.mark.parametrize('path,field,value', [('/csrf', 'csrfToken', 'CSRF-9ab1c2d3'),
                                          ('/oauth2/token', 'accessToken', 'abc.def.ghi'),
                                          ('/authorize', 'authorizationCode', 'CODE-9ab1c2d3')])
def test_issued_security_values_stay_outside_csv(path, field, value):
    r, _ = plan([entry('GET', path, response={field: value}),
                 entry('POST', '/verify', {field: value}, index=1)])
    assert value not in values(r)
    assert value in {c.value for c in r.correlations}
    intents = decide_intents(r.capture, build_lineage(r.capture), r.classification.verdicts)
    assert next(d for d in intents if d.value == value).action == ParameterAction.CORRELATE
