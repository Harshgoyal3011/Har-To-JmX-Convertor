"""Materialize accepted authentication dependencies; never discover new ones."""

from __future__ import annotations

import re
from urllib.parse import unquote

from har2jmx.correlate import ExtractorType

_STATE = re.compile(r"csrf|xsrf|session|requestverification|authenticity|authentication", re.IGNORECASE)
_AUTH_TOKEN = re.compile(r"(?:access|refresh|identity|id)[_.-]?token", re.IGNORECASE)
_HEADERS = {
    "authorization",
    "proxy-authorization",
    "x-csrf-token",
    "x-xsrf-token",
    "x-access-token",
    "x-auth-token",
}


def authentication_dependency(result, decision) -> bool:
    if decision.extractor == ExtractorType.COOKIE_MANAGER:
        return False  # JMeter already manages these cookies independently per thread.
    producer = result.capture.requests[decision.producer_index]
    field = decision.producer_location.split(":", 1)[-1].split(".")[-1]
    if _STATE.search(field) or _AUTH_TOKEN.search(field):
        return True
    if producer.classification.auth_candidate and (
        field.lower() in {"code", "state", "nonce", "tx", "token"}
        or re.search(r"token|cookie|challenge|transaction", field, re.IGNORECASE)
    ):
        return True
    if decision.producer_location.startswith("set-cookie:"):
        return True  # issued cookie reused outside CookieManager requires explicit state.
    for index in decision.consumers:
        for name, value in result.capture.requests[index].request.headers:
            if name.lower() in _HEADERS and (value == decision.value or value.endswith(" " + decision.value)):
                return True
    return False


def cookie_decoding_required(result, decision) -> bool:
    if not decision.producer_location.startswith("set-cookie:"):
        return False
    name = decision.producer_location.split(":", 1)[1]
    return any(
        n == name and raw != decision.value and unquote(raw) == decision.value
        for n, raw in result.capture.requests[decision.producer_index].response.set_cookies
    )


def add_cookie_normalization(parent, variable, subelement, string_prop):
    node = subelement(
        parent,
        "JSR223PostProcessor",
        {
            "guiclass": "TestBeanGUI",
            "testclass": "JSR223PostProcessor",
            "testname": f"Decode {variable} cookie value",
            "enabled": "true",
        },
    )
    for key, value in [
        ("scriptLanguage", "groovy"),
        ("parameters", ""),
        ("filename", ""),
        ("cacheKey", "true"),
    ]:
        string_prop(node, key, value)
    string_prop(
        node,
        "script",
        f"def value = vars.get('{variable}')\n"
        "if (value && !value.startsWith('NOT_FOUND_')) {\n"
        f"    vars.put('{variable}', java.net.URLDecoder.decode(value.replace('+', '%2B'), 'UTF-8'))\n"
        "}",
    )
    subelement(parent, "hashTree")


def auth_representations(result, decision):
    """Exact encoded consumer slots of an already accepted dependency."""
    for index in decision.consumers:
        req = result.capture.requests[index].request
        pairs = req.cookies + req.query + req.body.form + req.headers
        for _, value in pairs:
            raw = str(value)
            if raw != decision.value and unquote(raw) == decision.value:
                yield raw
        # Reuse the emitter's existing scheme-prefixed header slot semantics.
        for _, value in req.headers:
            parts = str(value).split(None, 1)
            if len(parts) == 2 and parts[1] != decision.value and unquote(parts[1]) == decision.value:
                yield parts[1]


def add_runtime_checks(parent, decisions, subelement, string_prop):
    """Reset and verify thread-local auth state at its producer, including failures."""
    names = [d.variable for d in decisions]
    if not names:
        return
    # Variable names are already sanitized by discovery. No captured token or
    # username/password is included in the Groovy script or global properties.
    literals = ", ".join("'" + name + "'" for name in names)
    # These are empty/sentinel declarations, never captured tokens. JMeter
    # copies UDVs into each thread; the producer then resets that thread's vars.
    args = subelement(
        parent,
        "Arguments",
        {
            "guiclass": "ArgumentsPanel",
            "testclass": "Arguments",
            "testname": "Authentication runtime variables",
            "enabled": "true",
        },
    )
    collection = subelement(args, "collectionProp", {"name": "Arguments.arguments"})
    for name in names:
        value = subelement(collection, "elementProp", {"name": name, "elementType": "Argument"})
        string_prop(value, "Argument.name", name)
        string_prop(value, "Argument.value", "NOT_FOUND_" + name)
        string_prop(value, "Argument.metadata", "=")
    subelement(parent, "hashTree")
    for tag, label, script in [
        (
            "JSR223PreProcessor",
            "Reset authentication state",
            f"[{literals}].each {{ name -> vars.put(name, 'NOT_FOUND_' + name) }}",
        ),
        (
            "JSR223Assertion",
            "Require fresh authentication state",
            (
                f"def missing = [{literals}].findAll {{ name -> !vars.get(name) || vars.get(name).startsWith('NOT_FOUND_') }}\n"
                "if (missing) {\n"
                "    AssertionResult.setFailure(true)\n"
                "    AssertionResult.setFailureMessage('Authentication extraction failed: ' + missing.join(', '))\n"
                "    prev.setStopThread(true)\n"
                "}"
            ),
        ),
    ]:
        node = subelement(
            parent, tag, {"guiclass": "TestBeanGUI", "testclass": tag, "testname": label, "enabled": "true"}
        )
        string_prop(node, "scriptLanguage", "groovy")
        string_prop(node, "parameters", "")
        string_prop(node, "filename", "")
        string_prop(node, "cacheKey", "true")
        string_prop(node, "script", script)
        subelement(parent, "hashTree")
