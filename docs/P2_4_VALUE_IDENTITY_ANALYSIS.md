# P2-4 value identity analysis (pre-edit)

**Final status: STOPPED under the user's Phase 1 stop rule. No production repair is shipped. R05 remains unfixed.** The original source bytes have been restored; rejected implementation and focused failure probes are preserved separately for review.

Baseline: `69bc53cd12dca4ce1eb6c5b7203a6b22d5f2b9a2`. The original 54 source files and all 202 input hashes are frozen under `../p2-4-value-identity-20261005/parent-engine` and its manifests. All 52 unseen, 76 frozen and 74 existing captures converted before editing.

## Complete lifecycle and equality uses

HAR is parsed by the reader and `ir/build.py` into typed JSON, decoded query pairs, headers, cookies, native multipart fields and indexed request events. `lineage/graph.py` inventories request/response slots, stringifies scalars and strips whitespace / percent-decodes them. Its JSON traversal discards list indices. `build_lineage` keys observations by normalized literal and chooses the earliest response as `first_producer`. That is candidate evidence, but currently also producer identity and consumer lookup.

`entities` associates instances with normalized scalar strings; `classify/value_engine.py` associates a literal with an entity and classifies each literal flow using the existing lifecycle policies. `correlate/decide.py` retrieves that flow by literal, assigns a variable and deduplicates by variable plus literal. `correlate/necessity.py` again retrieves the literal flow and applies emission policy. `validate/extractors.py` checks that the extractor resolves to the captured normalized literal, including refinement of ambiguous object paths; it cannot establish that another equal response occurrence is the intended owner.

`parameterize/intent.py` looks up literal flows to inventory approved input slots. `parameterize/decide.py` uses literal verdict lookup, entity/field column grouping and sample equality to consolidate columns. `emit/bindings.py` supplies P2-3 provenance-based CSV naming and namespace separation. This protection does not fix runtime ownership.

`emit/jmx.py:_build_sub_map` maps every accepted runtime literal globally to a variable. `_slot_apply` applies scoped CSV bindings but falls back to that global runtime map. `_sub_json` drops array indices; `_sub_path`, query/form arguments, `_apply_header`, manual cookies and `_sub_raw` consequently replace equal unrelated values. The same map is used for global headers. JMX therefore loses request, field, origin, type and position ownership even if a decision contained the correct producer request.

Equality is currently used for all six roles: candidate evidence, producer lookup, consumer lookup, runtime substitution, correlation deduplication and input consolidation. Only candidate evidence may retain literal buckets as an authoritative-free compatibility view.

## Reproduction and collision census

`R05_BEFORE.har` issues `orderId="1001"` at request 0 on `a.test`, issues `accountId="1001"` at request 1 on `b.test`, then consumes accountId at request 2. The baseline selects response 0 / orderId and emits `${orderId}` in request 2. Both producer identity and final substitution are wrong.

The complete pre-edit census found 47,990 multi-response literal buckets in unseen52, 5,099 in real76 and 1,664 in existing74, with 96,992 producer/consumer inventory rows. These counts include echoes, repeated reads and catalog observations. They are potential collisions, not independently established defects. Inventory truth is explicitly marked UNADJUDICATED where the capture does not establish a correct owner. No precision or recall percentage may be derived from these counts.

## Minimum repair boundary

Keep the literal inventory and every discovery/lifecycle/necessity policy unchanged. Add an occurrence index alongside that compatibility view. Each observation needs event index, request/response side, origin, exact structured path including array/pair index, original scalar type, original spelling and known representation transformation. Runtime ownership additionally records the selected producer and lifecycle decision. Retry events have distinct indices even when their URLs and payloads are identical.

Introduce one post-policy identity projection interface. It may restrict existing approved literal candidates to proven occurrence edges; an equal-literal alternate producer must pass the same existing policy on its own occurrence projection. It must never promote previously rejected literal candidates. Response echoes must be distinguished from new issuances by upstream request occurrences. Ambiguity is REVIEW, not an earliest/nearest-producer guess. Field correspondence is supporting evidence only, combined with producer operation, origin, structured/resource context and time ordering. Unfamiliar cases with no context remain unbound.

The emitter must consume exact approved occurrence bindings, including array index and original type. Authentication transformations continue to use the existing explicit representation helpers. CSV namespace ownership remains P2-3; equal inputs must retain source owners in their approved slots. Serialization, extractor expression generation, multipart, auth checks, redirect execution, retention and transactions are outside the repair boundary.

This boundary does not require a converter rewrite. If implementation or final-JMX evidence contradicts that assessment, stop and document the dependency rather than changing frozen policies.

## Experimental result and required boundary decision

The initial assessment above was too narrow. A post-policy occurrence index and exact JMX binding layer repaired the simple order/account collision, but failed to satisfy all contracts together. The original 481 tests could pass with compatibility exceptions, while focused R05 tests still showed an unrelated accountId receiving orderId and two independent equal name inputs sharing one CSV owner. Removing the unique-producer compatibility exception restored literal isolation but broke established userId and ecommerce orderId path reuse. The experiment was rejected, not shipped.

Concrete conflicts:

- The lifecycle verdict for a literal can be determined by an unrelated request-first occurrence or another entity's earliest response. A downstream binding layer cannot recover each independent occurrence's lifecycle from that one verdict.
- Classification's entity association is a literal-to-entity map. Equal independent IDs have already lost their entity owner before correlation naming occurs.
- Intent discovery and input-column consolidation attach all same-literal request occurrences to one decision. P2-3 correctly protects distinct column owners, but cannot separate owners that were already consolidated into one column.
- Equality-derived response echoes are insufficient provenance. Some established paths rely on response observations across a payment/receipt dependency; blindly keeping or discarding those occurrences either breaks a proven path or manufactures identity evidence.

The minimum next design needs occurrence-aware *inputs and lookup interfaces* for classification, entity association and parameter intent/consolidation, while retaining the actual decision rules. That may be feasible without rewriting the policies, but it exceeds the tested post-policy binding-only boundary. The current experiment does not prove it safe. Under the instruction to stop if broader lifecycle/parameterization changes appear necessary, work stopped before changing those modules. This is a request for a concrete scope decision, not a claim that an entire converter rewrite is required.

A follow-on repair should first project separate occurrence flows into unchanged policy functions, define explicit echo/transport provenance, and keep independent USER_INPUT owners before column consolidation. It should then repeat all 15 focused categories, fresh-value JMX resolution and all 202 captures. Do not use the rejected compatibility exceptions as an implementation template.

## Deliverables and limits

The complete evidence directory is `../p2-4-value-identity-20261005/`. It contains the requested collision CSV, occurrence and normalization JSON audits, parameterization/correlation impact files, final-JMX audit, before/after scorecard, restored-source pytest XML and source hash report. The Markdown identity model is a proposed model, not implemented behavior. Rejected source and tests are under `rejected-experiment/`; partial after-conversions and experimental pytest files are evidence only.

The 54,753 multi-response buckets and 96,992 inventory rows were fully inventoried; dependency truth remains UNADJUDICATED for unfamiliar corpus cases. Baseline conversion is 52/52 + 76/76 + 74/74 with zero crashes. No accepted repaired after-version exists, so repaired conversion, precision/recall, undefined-variable, false-correlation and fresh-value ownership claims cannot be made. Unknown ground-truth counts are explicitly null in the scorecard. The synthetic wrong producer and wrong consumer each remain one after restoration. FIXED BY IDENTITY MODEL is empty.

## Known defects outside this repair

Lifecycle false runtime classifications; numeric JSON substitution becoming strings and runtime JSON escaping; invalid JSONPath for unusual property names; unresolved/failed runtime consumers; raw JSON body query loss and form query/body fidelity; extractor health/readiness reporting. Occurrence identity does not establish business intent or live-server extraction success.
