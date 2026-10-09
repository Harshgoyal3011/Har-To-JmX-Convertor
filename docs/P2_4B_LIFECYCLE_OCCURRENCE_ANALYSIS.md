# P2-4B lifecycle occurrence analysis

**Status: stopped under section 9. P2-4B is not implemented or successful.** No production source or existing tests changed. P2-4A remains frozen, including its occurrence model. Correlation discovery/binding, JMX emission and P2-3 CSV binding remain untouched.

Parent is the complete P2-4A working-tree source: commit `69bc53cd12dca4ce1eb6c5b7203a6b22d5f2b9a2` plus P2-4A exports/module. All 55 source files and 202 input hashes were frozen before this analysis. The existing uncommitted P2-4A work is preserved, not reverted.

## Stop-rule evidence

The user requires both unchanged underlying policies and positive creation evidence, with UNKNOWN/REVIEW when operation evidence is insufficient. The current non-GraphQL lifecycle rule cannot meet both requirements, even after removing foreign equal-value occurrences.

The exact synthetic case is:

```http
POST https://app.test/rpc
Content-Type: text/xml

<Envelope><Body><GetAccount><lookup>existing</lookup></GetAccount></Body></Envelope>
```

```json
{"account":{"id":"1001","name":"Existing Account"}}
```

The synthetic contract defines this as a read of an existing account. The capture contains one request/response event and no downstream consumer. The engine nevertheless assigns `RUNTIME_GENERATED / CREATED_THIS_RUN`, confidence High, to `response.body:account.id`. Its reason is “created this run (POST 200), then reused downstream”, although its consumer list is empty.

The decisive rule in `classify/value_engine.py:395` accepts POST/PUT/PATCH when `status == 201 OR a creation verb matches OR NOT search`. `/rpc` does not match search. This rule supplies runtime ownership without positive read/create contract evidence. `classify/lifecycle.py` has operation semantics for GraphQL but no equivalent generic SOAP/RPC operation evidence. The meaning of `GetAccount` is stated by the probe contract, not something the current converter proves automatically.

Evaluating this event alone reproduces the result. There is no foreign producer or equal request input to remove. An exact occurrence has the correct request index, response identity, origin, type and account path, but those coordinates cannot change that existing branch. Even treating the operation as unresolved would require changing the branch to UNKNOWN. Silently replacing or overriding it with a post-processing gate would be a policy change, not an evidence lookup repair.

`STOP_RULE_PROBE.json` includes the complete capture, exact P2-4A occurrence identities, original verdict and minimum additional design. `SYNTHETIC_BOUNDARY_PROBES.json` includes the same POST read after a separate order creation to distinguish policy error from equal-literal contamination.

## Current lookup dependencies

| Semantic consumer | Authoritative literal use | Required occurrence boundary |
|---|---|---|
| Lifecycle | `ClassificationResult.by_value`, `classify_values` looping literal `ValueFlow`, earliest literal producer/request | Exact owner evidence with the owner's request/response context, preserving catalog and established reuse evidence |
| Entity association | `_build_value_entity_map`: scalar value → one entity/attribute, preferring identifiers | Entity record source event/side and typed object path, scalar occurrence and array position |
| Entity consolidation | `_build_instances`: entity name + captured identifier value → merged row | Explicit record-owner evidence; no equal-value merge across unrelated origins/events |
| Scope reclassification | Runtime literal set intersected with producer path/query literals | Approved scoped dependency evidence, rather than equality assigning another owner's scope |
| Parameter intent | `classify_intent` retrieves `lineage.by_value(v.value)`; one verdict supplies all request slots | Exact occurrence verdict and its permitted evidence; unrelated equal request slots remain independent |
| Parameter planning | Decision dictionaries by value; input columns setdefault by spelling and equal value | Logical owner key separate from names and captured samples |
| Single-row consolidation | Existing name + equal row value skips another column | Merge only with explicit common owner, otherwise independent columns/review |

No lookup above was changed in this phase. Replacing only the keys without defining the scoped evidence view would discard downstream reuse or silently retain equality-derived ownership. That is why diagnostics are not presented as a shipped occurrence-aware classifier.

## Synthetic occurrence inspections

Fourteen read-only cases cover all twelve requested categories, plus isolated and colliding POST-read policy probes: order/account 1001; two equal inputs; two entities with equal IDs; read response echo; creation/catalog collision; different hosts; different event indexes; array positions; header/body value; retry; same field with independent ownership; and equal values across related datasets.

Every case exports exact P2-4A occurrence records and legacy semantic outputs. Single-event policy evaluations are explicitly diagnostic: removing other events loses reuse/catalog context, so differences are not declared corrected lifecycle ground truth. No response/request edges or logical identity aliases are manufactured.

Two independent-input probe groups expose four distinct request occurrences assigned to two shared columns. Each group's steps have the same field and captured value but separate action ownership. `INPUT_COLLAPSE_INVENTORY.csv` records exact source occurrence IDs and the existing shared column. `ENTITY_OCCURRENCE_AUDIT.json` shows separate order/account record evidence alongside the one literal-based association. These defects remain unfixed after the stop.

## Minimum additional design

Before activation, define a generic operation-evidence interface that can express explicit read/list/query, create/write and unresolved contracts. Retain current GraphQL handling and established credential/session evidence. A non-search POST alone must cease to establish creation; unresolved operation contracts need UNKNOWN/REVIEW. Do not replace this with a `Get`/`Create` field-name dictionary or an application-specific rule. The interface needs an explicit evidence source and policy tests, rather than assumed business semantics.

This requires a concrete policy decision: permit replacing the current non-search POST creation fallback with positive operation-contract evidence and UNKNOWN behavior. That is the minimum policy change identified by the probe. A full converter rewrite is not proposed.

Once that rule is resolved, occurrence-based entity/intent interfaces can be designed with typed record paths and scoped evidence. Preserve unrelated policy rules, separate request owner identity from display/CSV names, and use explicit identity evidence for consolidation. Producer-consumer binding and JMX changes should remain later phases. Until then, keeping the old policy and claiming that read occurrences cannot inherit runtime state would be incorrect.

## Regression and deliverables

The parent suite passes **493 tests**, including all **12 P2-4A occurrence tests**. Source hashes confirm all 55 parent files are unchanged. The fresh run passes **52/52 unseen + 76/76 frozen + 74/74 existing captures**, with zero crashes. Parent/current lifecycle, entity, parameterization, correlation decisions, JMX XML (except the generated plan timestamp) and CSV bytes all match. This is regression validation of the unchanged parent, not validation of a repaired P2-4B engine.

Both runs contain 1,101 correlation candidates, 1,070 accepted correlations, 31 rejected candidates, 1,238 CSV columns, 511 materialized extractors, 2,129 samplers and 701 transaction controllers. Static checks find zero undefined request variables, zero CSV/runtime name collisions and zero duplicate CSV names. They find 41 extractors without a static request/header reference in both versions; these are existing findings, not newly introduced defects. Static liveness does not prove live execution health. The requested absence of *new* dead extractors is met; zero total dead extractors is not claimed.

The evidence package is `../../p2-4b-occurrence-semantics-20261006/` relative to this document. It contains the requested lifecycle/entity/parameter audits, input-collapse CSV, consolidation audit, scorecard, regression report and source hash report, plus full pytest XML and executable boundary probes.

Unknown corpus truth counts are null: repeated observations are not automatically ownership defects, and external business/dependency ground truth is unavailable. No correlation precision/recall improvement, zero total false correlation claim, repaired input ownership or occurrence-semantic API is reported. Regression metrics report changes relative to the parent separately from existing defects.

## Remaining defects

Lifecycle/semantic occurrence contamination, literal entity association, independent-input consolidation and the non-search POST-read rule remain. R05 runtime producer/consumer substitution is explicitly frozen and unfixed. JSON numeric typing/escaping, unusual JSONPath keys, failed runtime consumers, query/body fidelity and extraction health/readiness also remain outside this stopped phase.
