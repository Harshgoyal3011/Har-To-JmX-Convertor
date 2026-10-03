"""Operation semantics as lifecycle evidence, independent of values and domains."""

from __future__ import annotations

import re

from har2jmx.ir.normalized import BodyKind

# Strings/comments cannot introduce an operation. The scanner needs only the
# document's top-level definitions; it does not interpret application fields.
_TOKENS = re.compile(r'"""[\s\S]*?"""|"(?:\\.|[^"\\])*"|\#[^\r\n]*|[_A-Za-z][_0-9A-Za-z]*|[{}()]')


def graphql_operation_kind(request) -> str | None:
    """query/mutation/subscription/unknown; None means no GraphQL evidence.

    A POST is a transport choice, not creation evidence. Resolve operationName
    when multiple operations exist; an ambiguous document stays unknown.
    """
    body = request.request.body
    payload = body.json
    if body.kind != BodyKind.GRAPHQL or not isinstance(payload, dict):
        return None
    document = payload.get("query")
    if not isinstance(document, str):
        return "unknown"
    tokens = [t for t in _TOKENS.findall(document) if not t.startswith(('"', "#"))]
    operations = []
    depth = 0
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if depth == 0:
            if token in {"query", "mutation", "subscription"}:
                name = tokens[index + 1] if index + 1 < len(tokens) else ""
                operations.append((name if name not in {"{", "("} else "", token))
                index += 1
                while index < len(tokens) and tokens[index] != "{":
                    # Ignore object defaults inside operation variable declarations.
                    if tokens[index] == "(":
                        parens = 1
                        index += 1
                        while index < len(tokens) and parens:
                            parens += (tokens[index] == "(") - (tokens[index] == ")")
                            index += 1
                    else:
                        index += 1
                if index == len(tokens):
                    return "unknown"
                depth = 1
                index += 1
                continue
            if token == "fragment":
                index += 1
                while index < len(tokens) and tokens[index] != "{":
                    index += 1
                if index == len(tokens):
                    return "unknown"
                depth = 1
                index += 1
                continue
            if token == "{":
                operations.append(("", "query"))
        depth += (token == "{") - (token == "}")
        if depth < 0:
            return "unknown"
        index += 1
    if depth:
        return "unknown"
    selected = payload.get("operationName")
    matches = (
        [kind for name, kind in operations if name == selected]
        if selected
        else [kind for _, kind in operations]
    )
    return matches[0] if len(matches) == 1 else "unknown"


def graphql_schema_value(location: str) -> bool:
    """GraphQL's reserved introspection roots describe protocol configuration."""
    return location.startswith(("response.body:data.__schema.", "response.body:data.__type."))


def read_result_is_runtime_state(flow) -> bool:
    """Explicit state transport can be issued by a read; catalog shape cannot prove it."""
    return any(
        occurrence.location.startswith("request.cookie:")
        or (occurrence.location.startswith("request.body:")
            and re.sub(r"[^a-z]", "", occurrence.field.lower())
            in {"accesstoken", "refreshtoken", "csrftoken", "xsrftoken"})
        or (
            occurrence.location.startswith("request.header:")
            and occurrence.field.lower()
            in {
                "authorization",
                "proxy-authorization",
                "x-auth-token",
                "x-access-token",
                "x-api-key",
                "x-csrf-token",
                "x-xsrf-token",
            }
        )
        for occurrence in flow.consumers
    )
