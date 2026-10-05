"""Final business labels from captured operation evidence, never grouping rules."""
from __future__ import annotations

import base64
import json
import re
from urllib.parse import unquote

_TOKENS = re.compile(r"[A-Z]+(?=[A-Z][a-z]|\d|$)|[A-Z]?[a-z]+|\d+|[A-Z]+")
_VERBS = {
    "get": "View", "fetch": "View", "retrieve": "View", "load": "View", "list": "View",
    "view": "View", "read": "View", "show": "View", "find": "Search", "search": "Search",
    "lookup": "Search", "query": "Search", "create": "Create", "new": "Create", "add": "Add",
    "save": "Save", "update": "Update", "edit": "Update", "modify": "Update", "delete": "Delete",
    "remove": "Remove", "acknowledge": "Acknowledge", "confirm": "Confirm", "submit": "Submit",
    "approve": "Approve", "reject": "Reject", "cancel": "Cancel", "upload": "Upload",
    "download": "Download", "export": "Export", "import": "Import", "book": "Book",
    "reserve": "Reserve", "assign": "Assign", "change": "Change", "set": "Set", "print": "Print",
    "initiate": "Initiate", "complete": "Complete", "process": "Process", "register": "Register",
}
_PROTOCOL = {"api", "rest", "rpc", "gql", "graphql", "odata", "web", "ws", "service", "services"}
_JOIN = {"for", "by", "with", "to", "and", "of", "from", "in", "on"}
_EXT = re.compile(r"\.(?:json|xml|html?|csv|txt|aspx?|php|jsp|do|action|cgi|svc)$", re.IGNORECASE)
_SPECIAL = {"Login", "Logout", "Refresh Token", "Session", "Launch Application", "Checkout", "Payment"}


def tokenize(value):
    return [token for piece in re.split(r"[^A-Za-z0-9]+", value)
            for token in _TOKENS.findall(piece) if not token.isdigit()]


def _display(tokens):
    return " ".join(t if t.isupper() and len(t) > 1 else t[:1].upper() + t[1:] for t in tokens)


def _segments(request):
    from har2jmx.workflow.transactions import _strip_num_suffix

    segments = []
    for raw in request.request.path_segments:
        value = unquote(raw).split("?", 1)[0]
        if value.startswith("(S("):
            continue
        value = re.sub(r"\([^)]*\)$", "", value)
        value = _strip_num_suffix(_EXT.sub("", value))
        if not value or any(c.isdigit() for c in value) or value.lower() in _PROTOCOL:
            continue
        if any(c in value for c in "=&%#"):
            continue
        segments.append(value)
    return segments


def _vocabulary(capture):
    words = {}
    def keys(value):
        if isinstance(value, dict):
            for key, child in value.items():
                yield str(key)
                yield from keys(child)
        elif isinstance(value, list):
            for child in value:
                yield from keys(child)
        elif isinstance(value, str) and len(value) < 1000000:
            # A captured, valid base64 JSON representation supplies schema keys,
            # not guessed business values. It never changes response parsing.
            try:
                decoded = base64.b64decode(value, validate=True).decode("utf-8")
                if decoded.lstrip().startswith(("{", "[")):
                    yield from keys(json.loads(decoded))
            except (ValueError, UnicodeError):
                pass
    for request in capture.requests:
        if request.classification.excluded:
            continue
        values = _segments(request)
        if request.request.body.graphql_operation:
            values.append(request.request.body.graphql_operation)
        values.extend(keys(request.response.body.json))
        for value in values:
            if not re.search(r"[_\-.]|[a-z][A-Z]|[A-Z][A-Z][a-z]", value):
                continue
            for token in tokenize(value):
                if len(token) >= 2 and token.lower() not in _PROTOCOL:
                    words.setdefault(token.lower(), token)
    return words


def _lower_tokens(value, words):
    vocabulary = dict(words)
    vocabulary.update({word: word for word in _VERBS})
    vocabulary.update({word: word for word in _JOIN})
    memo = {}

    def paths(start):
        if start == len(value):
            return [()]
        if start in memo:
            return memo[start]
        results = []
        for end in range(start + 2, len(value) + 1):
            atom = value[start:end]
            if atom in vocabulary:
                results.extend((vocabulary[atom],) + tail for tail in paths(end))
            if len(results) > 2:
                break
        memo[start] = results
        return results

    splits = [parts for parts in paths(0) if len(parts) > 1]
    return list(splits[0]) if len(splits) == 1 else [value]


def _words(value, vocabulary):
    tokens = tokenize(value)
    if value.islower() and len(tokens) == 1:
        return _lower_tokens(value, vocabulary)
    return tokens


def _operation(request, vocabulary):
    body = request.request.body
    value = body.graphql_operation
    if not value and isinstance(body.json, dict) and body.json.get("jsonrpc") and isinstance(body.json.get("method"), str):
        method = body.json["method"]
        if method.lower() not in {"call", "execute", "dispatch", "invoke", "request"}:
            value = method
    if not value and body.kind.value == "soap":
        from har2jmx.workflow.transactions import _soap_operation

        value = _soap_operation(request) or ""
    segments = _segments(request)
    if value:
        return _display(tokenize(value)), False, "explicit_protocol_operation"
    value = value or (segments[-1] if segments else "")
    words = _words(value, vocabulary)
    if words and words[0].lower() in _PROTOCOL:
        words = words[1:]
    action = _VERBS.get(words[0].lower(), "") if words else ""
    noun = words[1:] if action else words
    reason = "captured_operation_tokens" if action else "method_and_resource"
    uncertain = False
    if not action:
        # Lowercase read prefixes are hypotheses; never blindly split write
        # prefixes such as booking -> book + ing.
        for prefix in ("retrieve", "search", "lookup", "fetch", "query", "load", "list", "view", "read", "show", "find", "get"):
            if value.lower().startswith(prefix) and len(value) > len(prefix) + 2:
                action = _VERBS[prefix]
                noun = _words(value[len(prefix):], vocabulary)
                uncertain = len(noun) == 1 and noun[0].islower()
                reason = "read_prefix_with_capture_lexical_evidence" if not uncertain else "opaque_read_operation"
                break
    if not action:
        # Preserve established labels when no stronger operation evidence is
        # captured. A name is not independent proof of an interaction boundary.
        from har2jmx.workflow.transactions import _name_transaction

        name, _ = _name_transaction(request)
        # If a case-preserving resource spelling can replace a demonstrably
        # collapsed noun, restore only its observed words, retaining the verb.
        if words and value:
            collapsed = value.lower()
            for old in name.split():
                if old.lower() == collapsed and len(words) > 1:
                    name = name.replace(old, _display(words))
        return name, True, "existing_method_resource_label_semantics_uncertain"
    if not noun and len(segments) > 1:
        noun = _words(segments[-2], vocabulary)
    if not noun:
        return action, True, "operation_without_observable_object"
    if any(t.islower() and len(t) >= 8 and t.lower() not in vocabulary
           and len(_lower_tokens(t, vocabulary)) == 1 for t in noun):
        # A captured lowercase operation can carry a recoverable schema prefix
        # and an opaque suffix. Show only independently evidenced prefix words;
        # never manufacture the suffix's meaning or print concatenated text.
        recovered = []
        for token in noun:
            if not token.islower() or len(token) < 8 or token.lower() in vocabulary:
                recovered.append(token)
                continue
            remainder = token
            prefix_words = []
            while remainder:
                candidates = [w for w in vocabulary if remainder.startswith(w)]
                if not candidates:
                    break
                longest = max(candidates, key=len)
                prefix_words.append(vocabulary[longest])
                remainder = remainder[len(longest):]
            if len(prefix_words) >= 2 and all(len(word) >= 4 for word in prefix_words):
                recovered.extend(prefix_words)
        noun = recovered or ["Operation"]
        uncertain = True
        reason = "partial_captured_word_boundaries_opaque_remainder"
    if not uncertain and noun and len(noun) == 1 and noun[0].lower() in _VERBS:
        uncertain = True
    # Existing plural spelling is retained; inflection is not a business noun
    # dictionary. Exact standalone action terminals already have stable labels.
    if value.lower() in _VERBS:
        from har2jmx.workflow.transactions import _name_transaction

        name, _ = _name_transaction(request)
        return name, False, "captured_terminal_operation"
    if any(token.lower() in _VERBS for token in noun):
        uncertain = True
    return (action + " " + _display(noun)).strip(), uncertain, reason


def _primary(capture, transaction, evidence):
    pool = [capture.requests[i] for i in transaction.business_indices]
    # An actual user navigation names its caused interaction; parser fetches,
    # auth continuations and secondary lookup calls remain supporting requests.
    for request in pool:
        headers = {key.lower(): value for key, value in request.request.headers}
        if headers.get("sec-fetch-dest") == "document" and headers.get("sec-fetch-user") == "?1":
            return request
    for request in pool:
        if evidence.get(request.index) == "changed_explicit_event_listener_call_site":
            return request
    return capture.requests[transaction.anchor_index]


def name_transactions(capture, transactions):
    from har2jmx.workflow.boundaries import boundary_evidence

    vocabulary = _vocabulary(capture)
    evidence = boundary_evidence(capture)
    identities = {}
    for transaction in transactions:
        original = re.sub(r" \(\d+\)$", "", transaction.name)
        if original in _SPECIAL or transaction.category == "Authentication":
            name, uncertain, reason = original, False, "existing_authentication_or_launch_semantics"
            primary = capture.requests[transaction.anchor_index]
        else:
            primary = _primary(capture, transaction, evidence)
            name, uncertain, reason = _operation(primary, vocabulary)
            transaction.category = "Business Action" if name.split()[0] in set(_VERBS.values()) - {"View", "Search"} else "Business View"
        if len(name) > 64:
            name = name[:64].rsplit(" ", 1)[0]
            uncertain = True
        transaction.name = name
        transaction.naming_confidence = "uncertain" if uncertain else "supported"
        transaction.naming_reasons = [reason]
        # This labels request ownership, never changes retention/lifecycle.
        from har2jmx.workflow.boundaries import event_sites

        primary_sites = event_sites(primary)
        transaction.supporting_indices = [
            i for i in transaction.request_indices if i != primary.index and (
                capture.requests[i].classification.excluded
                or capture.requests[i].classification.role.value in {"polling", "static", "telemetry"}
                or capture.requests[i].context.initiator == "parser"
                or (primary_sites and event_sites(capture.requests[i]) == primary_sites)
            )
        ]
        for index in transaction.request_indices:
            capture.requests[index].context.transaction = name
        segments = _segments(primary)
        # Only distinct captured static resource scopes qualify equal display
        # names. Repeated instances, query values and ordinals do not.
        scope = _display(_words(segments[-2], vocabulary)) if len(segments) > 1 else ""
        identities.setdefault(name, []).append((transaction, scope))
    for name, matches in identities.items():
        scopes = {scope for _, scope in matches if scope}
        if len(scopes) < 2:
            continue
        for transaction, scope in matches:
            if scope and scope.lower() not in name.lower() and len(name + " - " + scope) <= 64:
                transaction.name = name + " - " + scope
                transaction.naming_reasons.append("captured_distinct_resource_scope")
                for index in transaction.request_indices:
                    capture.requests[index].context.transaction = transaction.name
