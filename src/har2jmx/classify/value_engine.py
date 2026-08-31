"""Milestone 8 — value classification engine.

Classifies every significant value into one of four classes, from lineage (M7) + lifecycle +
entity association — never from field-name/shape alone:

    STATIC                 constant/config; leave hardcoded
    BUSINESS_MASTER_DATA   existed before this run (read/selected, or user input) → parameterize
    RUNTIME_GENERATED      created/issued during this run (token, session, new object id) → correlate
    UNKNOWN                insufficient evidence → flag for review, never silently wired

The decisive discriminator is lifecycle: was the value present in a request *before* any response
produced it (master data / user input), or first issued by the server this run (runtime)?
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum

from har2jmx.entities import discover_relationships
from har2jmx.ir.normalized import NormalizedCapture
from har2jmx.lineage import LineageGraph, ValueFlow, build_lineage
from har2jmx.patterns import CREATION_VERB_RE, GUID_RE, PAGINATION_TOKEN_RE, TOKEN_NAME_RE, USER_DATA_RE

_JWT_RE = re.compile(r"^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$")


class ValueClass(str, Enum):
    STATIC = "STATIC"
    BUSINESS_MASTER_DATA = "BUSINESS_MASTER_DATA"
    RUNTIME_GENERATED = "RUNTIME_GENERATED"
    UNKNOWN = "UNKNOWN"


class Lifecycle(str, Enum):
    CREATED_THIS_RUN = "created_this_run"
    EXISTING_BEFORE_RUN = "existing_before_run"
    USER_INPUT = "user_input"
    UNKNOWN = "unknown"


@dataclass
class ValueVerdict:
    value: str
    classification: ValueClass
    lifecycle: Lifecycle
    confidence: str                 # High | Medium | Low
    reason: str
    source: str = ""                # producing location (or first request location)
    consumers: list[int] = field(default_factory=list)
    entity: str | None = None
    entity_field: str | None = None
    is_identifier: bool = False
    producer_scope: frozenset = frozenset()   # producer path segments + query values (session-scope test)
    needs_correlation: bool = False           # dynamic value we could not auto-correlate → flag for a human


@dataclass
class ClassificationResult:
    verdicts: list[ValueVerdict]

    def by_value(self, value: str) -> ValueVerdict | None:
        return next((v for v in self.verdicts if v.value == str(value).strip()), None)

    def correlations(self) -> list[ValueVerdict]:
        return [v for v in self.verdicts if v.classification == ValueClass.RUNTIME_GENERATED and v.consumers]

    def parameters(self) -> list[ValueVerdict]:
        return [v for v in self.verdicts if v.classification == ValueClass.BUSINESS_MASTER_DATA]

    def unknowns(self) -> list[ValueVerdict]:
        return [v for v in self.verdicts if v.classification == ValueClass.UNKNOWN]

    def needs_correlation(self) -> list[ValueVerdict]:
        """Dynamic values that could not be auto-correlated and are actually sent in a request —
        the list a performance engineer must wire up by hand before running at load."""
        return [v for v in self.verdicts if v.needs_correlation and v.consumers]


def _is_secret(flow: ValueFlow) -> bool:
    if GUID_RE.search(flow.value) or _JWT_RE.match(flow.value):
        return True
    if any(TOKEN_NAME_RE.search(o.field) for o in flow.occurrences):
        return True
    if any(o.location.startswith("set-cookie:") for o in flow.occurrences):
        return True
    return False


def _build_value_entity_map(cap: NormalizedCapture) -> dict[str, tuple[str, str, bool]]:
    model = discover_relationships(cap)
    ident = {e.name: e.identifier for e in model.entities}
    out: dict[str, tuple[str, str, bool]] = {}
    for ent, rows in model.instances.items():
        for row in rows:
            for attr, val in row.items():
                key = str(val).strip()
                is_id = attr == ident.get(ent)
                # prefer an identifier association over a plain attribute
                if key not in out or (is_id and not out[key][2]):
                    out[key] = (ent, attr, is_id)
    return out


def _business_named(flow: ValueFlow) -> bool:
    return any(USER_DATA_RE.search(o.field) and not TOKEN_NAME_RE.search(o.field) for o in flow.occurrences)


# Search / filter / category selections a user makes — classic parameterization targets (vary the
# term per virtual user). A clearly-named field only; a bare generic "q" stays conservative.
_SEARCH_INPUT_RE = re.compile(
    r"^(?:query|search|searchterm|keyword|keywords|kw|term|cat|category|categories|tag|tags|brand|"
    r"genre|department|dept|section|collection)$", re.IGNORECASE)


def _is_search_input(flow: ValueFlow) -> bool:
    return any(o.side == "request" and _SEARCH_INPUT_RE.match(o.field or "") for o in flow.occurrences)


def _is_pagination_token(flow: ValueFlow) -> bool:
    """The producing field is a next-page/continuation handle (opaque state)."""
    if flow.first_producer is not None and PAGINATION_TOKEN_RE.search(flow.first_producer.field or ""):
        return True
    return any(PAGINATION_TOKEN_RE.search(o.field or "") for o in flow.producers)


# UI / display / config toggles: their value is a fixed enum the same for every user and every run, so
# varying it exercises nothing — parameterizing it just adds a noise CSV column. Matched as whole
# camel/snake words (so "modelId" is not mistaken for "mode", "border" not for "order").
_CONFIG_WORDS = {
    "layout", "sort", "sortby", "order", "orderby", "direction", "dir", "view", "mode", "theme",
    "display", "align", "alignment", "orientation", "format", "density", "variant", "sortorder",
    "sortdir", "sortfield", "viewmode", "tab", "panel", "skin", "style", "position",
}
_ENUM_VALUE_RE = re.compile(r"^[a-z][a-z0-9_]{0,19}$")
_KNOWN_ENUM_VALUES = {
    "asc", "desc", "true", "false", "grid", "list", "table", "card", "dark", "light", "auto",
    "none", "all", "default", "compact", "expanded", "horizontal", "vertical", "left", "right",
    "center", "top", "bottom", "enabled", "disabled", "on", "off", "yes", "no",
}
_WORD_SPLIT_RE = re.compile(r"[^A-Za-z0-9]+|(?<=[a-z0-9])(?=[A-Z])")


def _field_words(field: str) -> set[str]:
    return {w.lower() for w in _WORD_SPLIT_RE.split(field or "") if w}


def _is_config_constant(flow: ValueFlow) -> bool:
    """A UI/config enum on a config-named field — left hardcoded, never parameterized/correlated."""
    val = str(flow.value).strip()
    if val.lower() not in _KNOWN_ENUM_VALUES and not _ENUM_VALUE_RE.match(val):
        return False
    return any(_field_words(o.field) & _CONFIG_WORDS for o in flow.occurrences)


_CODED_ID_RE = re.compile(r"^[A-Za-z]{2,}[-_][A-Za-z0-9][\w-]*$")


def _is_opaque_handle(value: str) -> bool:
    """A random-looking, generated handle (mixed letters+digits, ≥8 chars) — not a plain id, count,
    slug, word, or structured business code. These are per-run server state (a quote ref, draft id,
    upload ticket) that expire, so a recorded value is stale. A structured coded id (PROD-4400,
    DOC-4451: a prefix + separator + code) is a stable identifier and is deliberately excluded — it
    belongs in a CSV so load spreads across the catalog, not correlated to a single instance."""
    val = str(value).strip()
    if _CODED_ID_RE.match(val):
        return False
    core = re.sub(r"[^A-Za-z0-9]", "", val)
    if len(core) < 8 or core.isdigit() or (core.isalpha() and core.islower()):
        return False
    has_upper = any(c.isupper() for c in core)
    has_lower = any(c.islower() for c in core)
    has_digit = any(c.isdigit() for c in core)
    return has_digit and (has_upper or has_lower) and (has_upper + has_lower + has_digit) >= 2


def classify_values(cap: NormalizedCapture, lineage: LineageGraph | None = None) -> ClassificationResult:
    lineage = lineage if lineage is not None else build_lineage(cap)
    value_entity = _build_value_entity_map(cap)
    req_by_index = {r.index: r for r in cap.requests}

    # How many distinct values each producer field emitted. A field that produced several values
    # (products[].productId → {5, 6, ...}) is a selectable catalog collection; a field that produced
    # exactly one (quoteRef → {Qz7...}) is a singleton handle. Array siblings share one location, so
    # a count > 1 marks the value as one-of-many (parameterize), a count of 1 as a singleton.
    producer_field_values: dict[str, set] = {}
    for f in lineage.flows:
        if f.first_producer is not None:
            producer_field_values.setdefault(f.first_producer.location, set()).add(f.value)

    verdicts: list[ValueVerdict] = []
    for flow in lineage.flows:
        # Short values (e.g. "1", "10") are too ambiguous to correlate or parameterize — they
        # collide across unrelated fields (a page number vs a stock count). Leave them literal.
        if len(str(flow.value)) < 3:
            continue
        if not flow.significant and flow.value not in value_entity:
            continue

        ent = value_entity.get(flow.value)
        entity_name = ent[0] if ent else None
        entity_field = ent[1] if ent else None
        is_id = ent[2] if ent else False
        consumers = flow.consumer_indices

        # A UI/config enum (layout=grid, sort=asc, view=list) is constant for every user and run —
        # leave it hardcoded rather than mint a noise CSV column. Decided before entity association,
        # which would otherwise pull it in as "master data".
        if _is_config_constant(flow):
            verdicts.append(ValueVerdict(
                value=flow.value, classification=ValueClass.STATIC, lifecycle=Lifecycle.UNKNOWN,
                confidence="Medium", reason="UI/config enum (same for every user) — left hardcoded, not parameterized",
                source=(flow.occurrences[0].location if flow.occurrences else ""),
                consumers=consumers, entity=None, entity_field=None,
            ))
            continue

        # Lifecycle turns on the EARLIEST occurrence overall, not merely "has a producer".
        # If the client sent the value before (or at) the response that returned it, the value is
        # client-originated (user input echoed back) — master data, NOT a runtime correlation.
        req_occs = [o for o in flow.occurrences if o.side == "request"]
        earliest_req = min((o.request_index for o in req_occs), default=None)
        earliest_resp = min((o.request_index for o in flow.producers), default=None)
        client_originated = earliest_req is not None and (earliest_resp is None or earliest_req <= earliest_resp)

        producer_scope: frozenset = frozenset()
        needs_corr = False
        if flow.first_producer is not None and not client_originated:
            # server-originated: the server introduced this value this run
            producer = req_by_index.get(flow.first_producer.request_index)
            source = flow.first_producer.location
            method = producer.method if producer else "GET"
            status = str(producer.status) if producer else ""
            path = producer.request.path if producer else ""
            search = _producer_is_search(producer) if producer else False
            if producer:
                producer_scope = _scope_tokens(producer)

            if source.startswith("response.regex:"):
                cls, life, conf = ValueClass.RUNTIME_GENERATED, Lifecycle.CREATED_THIS_RUN, "High"
                reason = ("found embedded inside an earlier response (server-issued, e.g. a token "
                          "wrapped in a string) and reused — correlated via a boundary extractor")
            elif _is_secret(flow):
                cls, life, conf = ValueClass.RUNTIME_GENERATED, Lifecycle.CREATED_THIS_RUN, "High"
                reason = "server-issued session/token/secret, reused in a later request"
            elif source.startswith(("response.location:", "response.header:")) or str(status).startswith("3"):
                cls, life, conf = ValueClass.RUNTIME_GENERATED, Lifecycle.CREATED_THIS_RUN, "High"
                reason = "issued in a response header / redirect (per-session: ETag/version, auth code, token), reused downstream"
            elif _is_pagination_token(flow):
                cls, life, conf = ValueClass.RUNTIME_GENERATED, Lifecycle.CREATED_THIS_RUN, "High"
                reason = ("server-issued pagination/continuation cursor consumed by the next page — "
                          "opaque state that only fits this dataset snapshot, so correlate per page, "
                          "never a static CSV value")
            elif (_is_opaque_handle(flow.value)
                  and len(producer_field_values.get(flow.first_producer.location, ())) <= 1):
                # a singleton opaque handle (quote ref, draft id, upload ticket) — server-issued this
                # run and expiring, NOT one of a selectable catalog set — so correlate the fresh value
                cls, life, conf = ValueClass.RUNTIME_GENERATED, Lifecycle.CREATED_THIS_RUN, "High"
                reason = ("opaque server-issued handle (singleton, not one of a catalog list) reused "
                          "downstream — per-run/expiring state, correlate it; a recorded value goes stale")
            elif method == "GET" or search:
                cls, life, conf = ValueClass.BUSINESS_MASTER_DATA, Lifecycle.EXISTING_BEFORE_RUN, "High"
                reason = f"returned by a {'search' if search else 'read'} ({method}) and reused — existing record selected, not created"
            elif method in {"POST", "PUT", "PATCH"} and (status == "201" or CREATION_VERB_RE.search(path) or not search):
                cls, life, conf = ValueClass.RUNTIME_GENERATED, Lifecycle.CREATED_THIS_RUN, "High"
                reason = f"created this run ({method} {status or ''}), then reused downstream"
            else:
                cls, life, conf = ValueClass.UNKNOWN, Lifecycle.UNKNOWN, "Low"
                reason = "produced then reused but lifecycle is ambiguous"
                needs_corr = True          # server-issued & reused but unclassified — a human should wire it
        else:
            # client-originated (first seen in a request; may be echoed back by the server later)
            source = (min(req_occs, key=lambda o: o.request_index).location
                      if req_occs else (flow.occurrences[0].location if flow.occurrences else ""))
            echoed = " (echoed back by the server, not generated by it)" if flow.producers else ""
            if _is_secret(flow):
                # A token / session id / GUID first seen in a REQUEST usually means the response that
                # issued it was not captured (an empty login body, or the flow starts mid-session).
                # It must NEVER be parameterized — a fixed token in a CSV makes every virtual user share
                # one stale session. Flag it for correlation instead (capture the issuing response, or
                # add a boundary extractor); never wire it as static test data.
                cls, life, conf = ValueClass.UNKNOWN, Lifecycle.UNKNOWN, "Medium"
                reason = ("token/session/secret sent in a request but its issuing response was not "
                          "captured — needs correlation (capture the response that returns it), "
                          "never safe as a static CSV value")
                needs_corr = True
            elif entity_name or _business_named(flow) or _is_search_input(flow):
                strong = _business_named(flow) or _is_search_input(flow)
                cls, life, conf = ValueClass.BUSINESS_MASTER_DATA, Lifecycle.USER_INPUT, "High" if strong else "Medium"
                reason = f"client-supplied business/master data (varies per user){echoed}"
            else:
                cls, life, conf = ValueClass.UNKNOWN, Lifecycle.UNKNOWN, "Low"
                reason = f"client-supplied value with no business/entity signal{echoed}"

        # A flagged value with no captured producer has no "consumers" (those require a producer), yet
        # it IS sent in requests — record those request indices so it can be reported and located.
        if needs_corr and not consumers:
            consumers = sorted({o.request_index for o in req_occs})

        verdicts.append(ValueVerdict(
            value=flow.value, classification=cls, lifecycle=life, confidence=conf, reason=reason,
            source=source, consumers=consumers, entity=entity_name, entity_field=entity_field,
            is_identifier=is_id, producer_scope=producer_scope, needs_correlation=needs_corr,
        ))

    _reclassify_user_scoped(verdicts)

    order = {ValueClass.RUNTIME_GENERATED: 0, ValueClass.BUSINESS_MASTER_DATA: 1,
             ValueClass.STATIC: 2, ValueClass.UNKNOWN: 3}
    verdicts.sort(key=lambda v: (order[v.classification], -len(v.consumers), v.value))
    return ClassificationResult(verdicts=verdicts)


def _scope_tokens(req) -> frozenset:
    """Whole-value tokens that scope a request: its path segments + its query values.

    A per-session value appearing here (e.g. /customers/CIF-778/accounts) proves the request is
    scoped to one authenticated user, so the records it returns are user-owned — not a shared catalog.
    """
    toks = {seg for seg in req.request.path.split("/") if seg}
    toks |= {str(val).strip() for _, val in req.request.query if str(val).strip()}
    return frozenset(toks)


def _reclassify_user_scoped(verdicts: list[ValueVerdict]) -> None:
    """Server-returned ids read from a per-user list must be correlated, not parameterized.

    A GET-returned, reused id is normally existing master data (parameterize from a CSV of known
    records). But when the producing request is itself scoped by a per-session correlated value
    (its path/query carries a runtime id such as ${cif}), the records it returns belong to whoever
    logged in — a static CSV id is valid for one user and 404s for every other. Correlating extracts
    the right id per user, so the script stays correct no matter how many logins the tester supplies.
    A shared catalog (`/products`) has no session value in its producer scope and is left untouched,
    preserving CSV load-spread across the catalog.
    """
    runtime_vals = {v.value for v in verdicts if v.classification == ValueClass.RUNTIME_GENERATED}
    if not runtime_vals:
        return
    for v in verdicts:
        if (v.classification == ValueClass.BUSINESS_MASTER_DATA
                and v.lifecycle == Lifecycle.EXISTING_BEFORE_RUN
                and v.consumers
                and v.producer_scope & runtime_vals):
            v.classification = ValueClass.RUNTIME_GENERATED
            v.lifecycle = Lifecycle.CREATED_THIS_RUN
            v.confidence = "High"
            v.reason = ("returned by a per-session request (its producer path/query carries a "
                        "correlated session id), so this id is user-owned — correlate per user, "
                        "not a shared CSV value that only fits one login")


def _producer_is_search(req) -> bool:
    keys = {k.lower() for k, _ in req.request.query}
    if keys & {"q", "query", "search", "keyword", "term", "filter"}:
        return True
    return bool(re.search(r"/(search|find|lookup|query|browse|list)", req.request.path, re.IGNORECASE))
