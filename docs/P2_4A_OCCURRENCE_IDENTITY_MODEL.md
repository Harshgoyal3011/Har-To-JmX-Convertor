# P2-4A occurrence identity foundation

Parent: `69bc53cd12dca4ce1eb6c5b7203a6b22d5f2b9a2`.

This phase adds an inspection-only identity substrate. It does not repair R05 or alter existing lifecycle, entity, parameter intent, correlation, JMX, CSV, authentication, redirect, multipart, noise or transaction behavior.

## Interface and activation

`har2jmx.lineage.build_occurrence_index(capture, lineage=None, *, capture_identity=None)` builds an independent index alongside the existing literal graph. It returns immutable `ValueOccurrence` records, exact `by_identity(id)` lookup, non-authoritative `literal_evidence(value)` lookup and JSON-compatible `inspect()` output. The engine and emitter do not invoke this API. Future callers can adopt occurrence lookup without changing compatibility callers in this phase.

Only `lineage/__init__.py` exports and the new `lineage/occurrences.py` module change production source. Every existing behavioral module and test remains byte-identical to the parent.

## Identity dimensions

An occurrence ID hashes version-independent capture-local coordinates: capture scope, event index, request/response side, transport location, typed structured path, pair ordinal, original scalar type and representation kind. IDs never use the normalized literal or field name alone. The default capture scope fingerprints ordered captured exchanges; callers can provide a persistent capture ID. Event indices distinguish identical retries. IDs are stable across repeated inspection of the same capture; supplying a persistent capture scope also avoids changing IDs when an edited capture's content fingerprint changes.

Each record preserves event/request identity, request index, side, canonical origin and host, source request identity, source response identity on response observations, structured path, array indices, pair index, scalar type, available spelling, normalization, representation kind and explicit local transforms. A response identity identifies the observed response event; it does not claim that event issued a runtime value. A request occurrence's source response identity is null because this phase establishes no producer/consumer dependency.

Paths use typed components, so `["items", 0, "id"]`, `["items", 1, "id"]` and `["items.id"]` remain distinct. Pair indexes preserve duplicate query/header/form/cookie positions. JSON integer, number, string, boolean and null retain original types.

## Representation and evidence

The compatibility bucket follows the existing `_norm` inventory. Membership means supporting equality evidence, never ownership. Observations outside legacy candidate discovery have a null compatibility bucket; inspection includes full JSON arrays and scalar lists without expanding correlation candidates or modifying traversal policies.

URL path/query spellings are retained from the original URL. Known URL percent/form decoding is named explicitly. Header credential payloads record `credential_scheme_removed` and point to their exact header representation parent. Body/header equality alone establishes no shared logical identity. Percent decoding and whitespace trimming used by compatibility normalization are labelled as compatibility transforms, rather than silently asserting application provenance.

JSON lexical escapes, quote delimiters and numeric exponent spelling have already been lost in the normalized IR. `spelling_source=decoded_json_scalar` states that limit; it does not claim a raw JSON lexeme. Form/cookie/header values carry the spelling available in the IR. XML/HTML/embedded regex/catalog observations absent from direct IR slots retain legacy coordinates and ordinal identities, with original type `unknown`; no array position or producer relationship is guessed.

## R05 demonstration

The probe issues orderId="1001" on producer A and accountId="1001" on producer B. Both occupy literal bucket "1001", but their occurrence IDs, response IDs, origin and field paths differ. The account consumer is a third independent occurrence. The existing engine still selects orderId and emits `${orderId}` for that account consumer. This is the intentionally preserved defect; P2-4A makes its distinct observations inspectable without claiming a repair.

## Validation and artifacts

All 52 unseen, 76 frozen and 74 existing captures convert. Parent/current comparison covers request classification/order, transactions, lifecycle/entity classification, correlation candidates/decisions/rejections, parameterization before/after emission, authentication, redirects, multipart IR, extractor checks, replay metrics and lineage. All match. CSV bytes match. JMX XML matches with only its generated TestPlan minute timestamp normalized. No request expression, sampler, transaction or extractor changes.

The suite passes 493 tests: the original 481 plus twelve focused foundation tests. Focused coverage includes R05, hosts, event indexes/retries, array/scalar-array positions, dotted keys, scalar types, header/body representations, encoded/decoded duplicate query pairs, deterministic inspection, value-independent coordinates under persistent capture scope, duplicate transport pairs, nested percent encoding and unchanged decisions/JMX. Inspection does not mutate the capture or literal graph.

Artifacts are under `../../p2-4a-occurrence-identity-20261005/` relative to this document's directory: VALUE_OCCURRENCE_SCHEMA.json, OCCURRENCE_INDEX_AUDIT.json, IDENTITY_COMPATIBILITY_AUDIT.json, R05_FOUNDATION_PROBE.json and its JMX, SOURCE_CHANGE_REPORT.json, REGRESSION_HASH_REPORT.json and full-pytest.xml. Per-capture compressed debug JSON exports the first 100 records showing spelling → identity → compatibility bucket; every occurrence is audited. The complete debug view remains available through `inspect()`.

## Deliberately deferred

No logical owner aliases, producer/consumer edges, identity-aware classification/entity association, parameter ownership splitting or runtime substitution changes are introduced. R05 and previously documented lifecycle, numeric JSON typing, JSONPath, failed consumers, query/body fidelity and extraction-readiness defects remain outside this phase.
