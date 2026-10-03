# P1-4: content-aware business request retention

Parent: P1-3 commit `0f009ac`. Only the request-role classifier and its new
content-evidence helper change. Correlation discovery/matching, lifecycle code,
authentication, redirects, parameterization mechanics and transaction detection
remain frozen. Earlier uncommitted parameterization work is excluded from this
commit and separately controlled during validation.

## Analysis before implementation

Both original NASA Images workflows contain a search followed by selection:

| HAR | Request | Response | Before |
|---|---|---|---|
| `nasa-images-1.har` | 1: `GET /asset/PIA12235` | HTTP 200 JSON resource catalog | STATIC, excluded |
| `nasa-images-2.har` | 1: `GET /asset/NHQ201905310037` | HTTP 200 JSON resource catalog | STATIC, excluded |

The response contains a collection self-link and a list of resource links.
Request 0's search returns the selected identity; request 1 retrieves its asset
catalog. The catalog describes image representations and metadata; it is not a
rendered image. The original benchmark's manual noise analysis labels both
request-1 exclusions as wrongly removed business requests.

`_is_static()` previously returned immediately when the path matched `/asset/`,
before considering the structured response. Consequently each final JMX
contained only its search sampler, losing the selection request.

The full pre-change audit covered 150 HARs. Sixty static-path responses were
structured: two NASA catalogs, 56 SVG resources, and two Systech JSON bootstrap
configuration requests. This evidence rules out a generic JSON/XML rescue.
The original HARs and source snapshot were frozen before implementation.

## Surgical decision change

Static-looking paths and extensions can be reconsidered using a parsed response
contract and HTTP role evidence:

- A self-described resource with a collection of links, including standard HAL
  navigation controls, is catalog/API evidence.
- A structured collection of records can represent application data when no
  stronger telemetry or rendering role is present.
- Singleton/nested records need additional request evidence: an API path,
  structured input, or an actual selector reused in the response. An unrelated
  cache-busting query does not establish data intent.
- XML records require an API/structured-input/query role. HTML and SVG markup
  do not establish API content.

Existing telemetry/vendor/third-party precedence remains before static checks.
Browser rendering MIME, rendering fetch destinations and no-cors beacon/render
transport prevent content-based rescue. Empty bodies, invalid JSON/XML, scalar
acknowledgements and flat bootstrap configuration are not rescued merely by
their content type. URL-like payload text is parsed defensively.

No application names, domain path lists, new hostname policies, field-name
blacklists, payload-size thresholds or new correlation heuristics are added.
Self-link URL comparison establishes resource identity, not host allowlisting.
The existing static/noise architecture and pattern definitions remain intact.

## Before/after request-retention scorecard

| Measure | Before | After |
|---|---:|---:|
| Frozen real workflow conversions | 76/76 | 76/76 |
| Existing mixed HAR conversions | 74/74 | 74/74 |
| Crashes | 0 | 0 |
| Confirmed business requests wrongly removed | 2 | 0 |
| Known noise retained, out of 261 original labeled requests | 11 | 11 |
| Static requests excluded, combined corpora | 535 | 533 |
| Telemetry requests excluded, combined corpora | 182 | 182 |
| Confirmed false correlations | 1 | 1 |
| New false correlations | — | 0 |
| Accepted auth dependencies materialized | 38/38 | 38/38 |
| Explicit current-Location transports materialized | 4/4 | 4/4 |
| Dead extractors / undefined variables | 0 / 0 | 0 / 0 |

The manual labels come from the existing `NOISE_ANALYSIS.json` and
`CORRELATION_NEGATIVE_GROUND_TRUTH.json`; labels were not regenerated from the
converter's decisions. The known-noise count is limited to the original labeled
real benchmark, not a claim that every request in the mixed corpus has ground
truth. The 11 retained noise requests are existing failures, not newly retained
noise introduced by this fix.

Only `nasa-images-1` and `nasa-images-2` change request roles and JMX. Each gains
one asset-catalog sampler and one sampler-owned response assertion in its
existing Search controller. Existing samplers, ordering and controller names
remain unchanged; 148/150 normalized JMX files are identical. The retained
selected identity reaches the unchanged test-data policy, so NASA's CSV gains
its selected identity alongside the search term. This is the expected effect
of restoring a previously excluded consumer, not an input-coverage change.

## Protected decisions and explicit limits

Every accepted correlation, necessity audit and extractor check is identical
before/after across both corpora. The 38 accepted auth dependencies and four
Location transports remain materialized. The nine redirect-policy workflows
have identical JMX. Countries' existing-data classification and CSV consumer
remain unchanged. Source hashes show only `classify/request_noise.py` changes
among pre-existing files.

Strict equality of **all lifecycle report outputs** is not achieved. Two unused
NASA search self-URLs change from runtime to existing data because the unchanged
lifecycle classifier aggregates distinct values at `collection.href`; retaining
the asset response adds a second value at that location. Neither has a consumer,
accepted correlation or CSV binding. Existing lifecycle decisions for values
with consumers are identical. Additionally, retained response fields become
new inventory values. These output deltas are explicitly recorded in
`CORPUS_REGRESSION.json`; lifecycle code is not altered to suppress them.

The remaining confirmed Automation Exercise false correlation is advertising
identifier `ca-pub-1677597403311019`, produced at request 0 and consumed by the
same nine requests as the parent. Its request roles, correlations and final JMX
are identical. Repairing that pre-existing advertising classification would
broaden this content-retention change and is deferred.

The parent also has six verified non-auth materialization gaps and 13 unresolved
non-auth extractors. These counts and affected dependencies remain unchanged.
This validation does not claim absolute replay readiness or universal lifecycle
output equality. No live replay was required or claimed for this retention fix.

## Regression evidence

The full checkout passes 443 tests; isolated committed P1-3 plus this change
passes 419 tests, including the unchanged P1-1/P1-2/P1-3 suites. The 34 new cases
cover real NASA captures separately from synthetic role mechanics: unfamiliar
fields, JSON/GeoJSON/OData records, GraphQL, XML/SOAP, HATEOAS, nested records,
bootstrap/metric negatives, known telemetry, no-cors/rendering roles, SVG/JS/HTML,
malformed content and actual final JMX sampler presence. Lint passes for new
files and the modified import block.

Workspace `p1-retention/` contains the requested reports:

- `REQUEST_RETENTION_SCORECARD.json`: before/after counts and ground-truth scope.
- `CHANGED_REQUEST_AUDIT.json`: original HAR, request, complete response content,
  before/after reasons and generated JMX path.
- `FINAL_JMX_REGRESSION.json`: added sampler, preserved samplers/controllers and
  assertion counts; original JMX and CSV remain in before/after folders.
- `PROTECTED_DECISIONS.json`, `CORPUS_REGRESSION.json`, and
  `COMMIT_CORPUS_REGRESSION.json`: accepted decision comparisons and incidental
  unused lifecycle deltas, including the isolated committed engine comparison.
- `AUTOMATION_ADVERTISING_AUDIT.json`, `KNOWN_NOISE_RETENTION.json`,
  `MATERIALIZATION_SUMMARY.json`, and `REDIRECT_JMX_AUDIT.json`: explicit negatives
  and protected final-JMX dependencies.
- `FREEZE.json`, `STATIC_STRUCTURED_AUDIT_BEFORE.json`, and both pytest XML
  reports: source snapshot, pre-implementation audit and full test results.

Raw captures and credentials are excluded from the source commit.
