# P1-2: redirect/session execution correctness

The parent is P1-1 commit `1154d59`. P1-2 changes only redirect emission policy;
P1-1 authentication helpers, cookie extraction, correlation discovery/matching,
parameterization, noise classification and transaction detection are unchanged.

## Analysis before source changes

The original real TripPin HARs contain four observed redirect edges:

| HAR | Producer | Captured target | Location |
|---|---|---|---|
| odata-trippin-1.har | 0: GET People | 1: GET People | `/V4/(S(dqive5j4zmslzajkl2xtvlww))/TripPinServiceRW/People?$top=2` |
| odata-trippin-1.har | 2: GET traveler Trips | 3: GET traveler Trips | `/V4/(S(0iwfrsysqr3rz1x5htlgfkcy))/TripPinServiceRW/People('russellwhyte')/Trips` |
| odata-trippin-2.har | 0: GET Airports | 1: GET Airports | `/V4/(S(aodf1eso3e1q2h4j5rgbbac3))/TripPinServiceRW/Airports?$top=2` |
| odata-trippin-2.har | 2: GET selected Airport | 3: GET selected Airport | `/V4/(S(v4zlzzgkqflrhwjeacz32kgq))/TripPinServiceRW/Airports('KSFO')` |

Each producer returns HTTP 302. Its Location matches the next captured request.
The generated plan emits all four entries per HAR with `follow_redirects=true`.
During replay JMeter follows the fresh runtime Location, then the separate
captured-target sampler requests the old session URL. Status assertions can pass
for both exchanges despite using two different sessions.

Existing lineage exposes Location query fields and dynamic last path segments.
These session values are embedded in an intermediate path segment; no accepted
correlation covers them. The emitter previously considered only `from_redirect`
correlations when disabling following. It did not account for observed redirect
targets otherwise. This is an execution ownership defect; solving TripPin does
not require changing correlation discovery.

Before implementation, all 150 original HARs were inspected: 27 redirect
responses occur in 14 workflows. The analysis and pre-change source hashes are
retained in workspace `p1-redirects/ANALYSIS_BEFORE.json` and `FREEZE.json`.

## One authoritative execution path

The emission policy links a 301/302/303/307/308 Location to a later HAR request
only when the resolved URL and expected redirect method match. It uses actual
request/response evidence, without application names or session URL patterns.

A complete chain can be followed by JMeter when its hops are consecutive
GET/HEAD requests in the same transaction and origin, with equivalent replayed
headers, no required explicit extractors or approved target CSV bindings, and
no subsequent reuse of the target path. Captured targets owned by that follower
are omitted. JMeter then handles runtime Location and per-thread cookies at
every hop. Redirects without a recorded target retain existing following behavior.

When any hop requires explicit execution, all earlier observed hops remain
explicit. Each source disables following, preserving intermediate response scope.
Already accepted Location correlations retain their original extractors and
consumer substitutions. Approved CSV target bindings also retain their existing
request representation. Other explicit targets use a transport extractor for
the whole current Location and a thread-local URI resolution postprocessor.
The captured target URL is absent from those sampler paths. Wire percent encoding
is retained; queries are carried by the runtime URL; method-preserving JSON and
form bodies remain on the explicit target. Missing Location fails the source
and stops that thread. No authentication variables or shared properties change.

Transaction names, boundaries, ordering and assertion configuration are preserved.
The expected sampler count changes only where redirect targets are already
executed by a follower. A single response assertion on that follower covers the
redirect result; the existing assertion policy itself is unchanged.

## Results

| Measure | Before | After |
|---|---:|---:|
| Frozen real workflows converted | 76/76 | 76/76 |
| Additional existing mixed HARs converted | 74/74 | 74/74 |
| Conversion crashes | 0 | 0 |
| TripPin samplers, both workflows | 8 | 4 |
| TripPin duplicate captured target samplers | 4 | 0 |
| Explicit current-Location transport consumers, corpus | 0 | 4 |
| Accepted auth dependencies materialized | 38/38 | 38/38 |
| Stale accepted auth literals | 0 | 0 |
| Dead extractors, both corpora | 0 | 0 |
| New false correlations | — | 0 |
| Protected decision regressions | — | 0 |

Only six JMX files change: both TripPin workflows; `sample_saml.har` and
`complex_saml.har`; the existing Systech capture; and the existing BlazeDemo
capture. The nine workflows with an identified execution policy have their
actual JMX inspected for ownership, following flags, producer extractor scope,
runtime target references, controller names and assertion settings.

The 76-workflow benchmark and 74 existing HARs remain unchanged. Every accepted
correlation identity, producer, consumer, extractor expression, parameterization
result, request classification and transaction model matches the frozen P1-1
working baseline. File hashes confirm only `emit/jmx.py` changes among existing
source files; the redirect policy and tests are new files.

The checkout passes 383 pytest tests, including 16 new generated-JMX redirect
tests and the unchanged 20 P1-1 authentication tests. The isolated committed
P1-1 plus P1-2 source, without earlier uncommitted parameterization changes,
passes 359 tests. Lint passes for the two new Python files.

## Live and mechanical replay evidence

Both permitted public TripPin workflows were replayed with JMeter 5.6.3, one
user/iteration. Each follows two actual HTTP 302 responses to two fresh session
URLs, then receives the expected HTTP 200 OData JSON. The captured session
targets are absent from the plan and replay. Request counts, Locations and
business response bodies are inspected, beyond response status alone. JTL
includes aggregate redirect samples and their child exchanges; aggregate and
child body copies are not counted as independent business calls.

An initial live attempt failed because the sandbox denied outbound sockets.
After approved outbound replay, both workflows passed; initial trial JTLs are
preserved. This is a smoke replay, not a public-service load test.

The separately labeled local synthetic replay tests both automatic and explicit
execution with two VUs over two iterations. Each mode records exactly four
redirects and four target exchanges, with four distinct session URLs, preserved
percent encoding and no captured target. Explicit execution preserves the
request-specific business header. All exchanges pass; synthetic flows are not
counted as real workflows.

## Acceptance limits retained from the baseline

The required absolute 100% materialization of *all* accepted correlations is
not met in the frozen baseline and remains unmet. The broader independent audit
finds 15 unresolved non-auth extractors and six verified non-auth dependencies
with a hardcoded representation or a missing consumer reference. Examples:
`rest-api-objects-1/2` retain a created object URL in a Referer header;
the existing Systech capture's `tx` has an embedded consumer; the existing
BlazeDemo capture has `cart`, `account`, and `referer` representations.
Those findings and counts are identical before/after. They require separate
materialization work; P1-2 does not repair unrelated consumer matching.

The three previously confirmed false correlations also remain unchanged.
There are zero new false correlations or materialization regressions. The
38 accepted auth dependencies and the four new Location transports materialize
completely. This result proves the observed TripPin defect is fixed; it does not
claim universal production replay readiness or fresh state for unrecognized
dependencies elsewhere in an unfamiliar flow.

All per-workflow evidence is in workspace `p1-redirects/`: `before.json`,
`after.json`, `CORPUS_REGRESSION.json`, `REDIRECT_JMX_AUDIT.json`,
`before-materialization.json`, `after-materialization.json`,
`MATERIALIZATION_SUMMARY.json`, `pytest-final.xml`, `pytest-commit.xml`,
`LIVE_REPLAY.json`, and `LOCAL_REPLAY.json`. Replay folders retain generated
JMX, JTL, response headers/bodies and logs. Raw HARs and captured credentials
are excluded from the source commit.
