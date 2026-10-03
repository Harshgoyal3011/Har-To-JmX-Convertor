# P1-3: runtime creation versus existing data

Parent: P1-2 commit `0479c95`. This change is confined to value lifecycle
classification between lineage discovery (M7) and correlation decisions (M9).
It preserves discovery/matching, authentication, redirect emission,
parameterization mechanics, noise classification and transaction detection.

## Root cause and pre-change evidence

In the original real `countries-graphql-5.har` and `countries-graphql-6.har`:

| Request | Operation | Evidence | Expected treatment |
|---|---|---|---|
| 1 | Introspection query | `data.__schema` describes types/capabilities | Static configuration |
| 2 | `Find($code:String!)` | Reads a country collection using EU/AS supplied by the scenario | Existing catalog |
| 3 | `Details($code:ID!)` | Supplies AD/AE selected from request 2's response | Existing test-data policy: parameterize selected identity |

The engine's search detection considered URL/query fields, without resolving
the GraphQL document. Request 2 uses HTTP POST; the lifecycle fallback treated
any non-search POST as creation. AD/AE became `created_this_run` with accepted
`countryCode` correlations. Extractor verification rejected `$..code`: 25
response matches cannot provide a stable runtime selector. No extractor or
consumer variable appeared in the final JMX; the captured selected code remained.

The existing confirmed negative ground truth labels request 3's selected code
as test input. This is a classification error, not justification to change
matching or force a catalog identity into an extractor.

Before source changes, both corpora were converted and the working engine was
copied with SHA-256 hashes. The parent commit was also validated independently,
excluding earlier uncommitted parameterization work.

## Small operation-based decision

The classifier resolves the selected GraphQL `query`, `mutation`, or
`subscription`, including `operationName` in multi-operation documents.
Comments, strings, fragments and variable defaults do not introduce operations.
Missing, ambiguous or unbalanced operation documents remain unresolved.

For response-first values from a query:

- Reserved schema/introspection roots are static configuration.
- Catalog collection or discovered entity evidence establishes existing data.
  Existing selection policy decides whether an actual consumer needs CSV data.
- Existing cookie, credential-header, token-exchange-body and pagination-state
  evidence retains the runtime path. A read can issue authentication state.
- Without entity/catalog or credential evidence, the value becomes UNKNOWN and
  reaches REVIEW. POST, response origin, reuse and identifier shape do not prove
  creation.

Mutation creation behavior, request-first input/echo behavior, and existing
user/session scope policy remain unchanged. No application names, domain field
lists, length/entropy thresholds or across-run comparisons are introduced.
The existing entity model and position-aware lineage provide role/reuse evidence;
their discovery is unchanged. This resolves the demonstrated transport-versus-
operation error; it does not claim to infer every proprietary RPC lifecycle.

## Before/after classification scorecard

| Measure | Before | After |
|---|---:|---:|
| Frozen real workflows converted | 76/76 | 76/76 |
| Additional existing mixed HARs converted | 74/74 | 74/74 |
| Crashes | 0 | 0 |
| Countries accepted false correlations | 2 | 0 |
| Confirmed false correlations, frozen real benchmark | 3 | 1 |
| Countries selected inputs represented in final JMX | 0/2 | 2/2 |
| Accepted authentication dependencies materialized | 38/38 | 38/38 |
| Explicit current-Location transports materialized | 4/4 | 4/4 |
| Stale accepted authentication literals | 0 | 0 |
| Dead extractors / undefined variables | 0 / 0 | 0 / 0 |
| New false correlations / protected regressions | — | 0 / 0 |

403 previously runtime-classified values change in five workflows: 296 schema
configuration values become STATIC, 105 catalog/entity values become existing
master data, and two unsupported read values become UNKNOWN. These are observed
classification transitions, not 403 newly asserted ground-truth cases.

Only the two Countries JMX files change. Each selected identity is supplied by
the existing CSV policy; request 3's JSON `variables.code` is `${code}`. There is
no `countryCode` reference or JSON extractor. The continent input and country
selection remain separate inputs despite sharing a field name. CSV columns
increase from 2 to 3 in the working checkout, or 4 to 5 in the isolated committed
engine, because the missing selected identity is now included. Earlier input-
coverage/configuration issues remain outside P1-3.

The other changed classification reports are `tests/fixtures/sample_graphql.har`,
`tests/fixtures/sample_mini.har`, and `examples/graphql_rickandmorty.har`; their
JMX and datasets are identical before/after. Every surviving accepted correlation
keeps its exact producer, consumers, expression and decision. All 150 lineage
graphs, request roles and transaction models are identical. Source hashes protect
the frozen authentication, redirect, emitter, parameterizer and noise code.

## Validation and remaining baseline limits

The checkout passes 409 tests; isolated parent-plus-P1-3 source passes 385 tests.
The 26 new lifecycle cases inspect generated JMX for existing selections,
created identities, query-issued access/refresh credentials, introspection,
request-first echoes and UNKNOWN review; they also exercise operation resolution.
The unchanged P1-1 and P1-2 suites run in both full suites. Lint passes for new
Python files and the modified import block; unrelated existing lint findings
are retained.

Both 150-HAR comparisons inspect actual final JMX. The nine redirect-policy
workflows have identical JMX and retain one execution path. All accepted auth
dependencies retain verified producer-owned extractors, runtime consumer
references, no stale literals and failure guards. No live replay is claimed for
P1-3; this is a classification and generated-artifact regression validation.

The broader baseline still contains six verified non-auth materialization gaps
and 13 unresolved non-auth extractors after removing the two erroneous Countries
candidates. Examples are `rest-api-objects-1/2` Referer representations, the
existing Systech capture's embedded `tx`, and BlazeDemo's `cart`, `account` and
`referer` representations. These are unchanged, so absolute 100% materialization
of all accepted correlations remains unmet. The remaining confirmed false
correlation is Automation Exercise's advertising identifier. P1-3 introduces
none and does not repair unrelated retention or consumer-matching defects.

Workspace `p1-lifecycle/` retains `FREEZE.json`, original before/after generated
JMX and CSV, `CLASSIFICATION_AUDIT.json/csv`, `CLASSIFICATION_SCORECARD.json`,
`CORPUS_REGRESSION.json`, `COMMIT_CORPUS_REGRESSION.json`,
`MATERIALIZATION_SUMMARY.json`, `REDIRECT_JMX_AUDIT.json`, per-workflow
materialization evidence and both pytest XML reports. Audit entries cite the
original HAR, producer request, response location, actual consumer location,
classification reason and final JMX. Raw captures and credentials are excluded
from the source commit.
