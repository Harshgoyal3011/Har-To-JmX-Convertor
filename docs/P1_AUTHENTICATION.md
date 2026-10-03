# P1-1: fresh authentication extraction and consumption

This change fixes authentication replay using accepted dependencies. It does
not change correlation discovery, producer/consumer selection, parameterization,
noise classification, transaction detection, or redirect execution policy.

## Root cause established before implementation

The frozen real workflow `dummyjson-1.har` has these requests (zero-based):

| Request | Role |
|---|---|
| 0: GET /users/1 | Obtain documented sandbox user data |
| 1: POST /auth/login | Produce accessToken and refreshToken |
| 2: GET /auth/me | Consume accessToken in Authorization |
| 3: POST /auth/refresh | Consume refreshToken |

`ir/build.py` parses the access cookie correctly. Lineage selects its
`set-cookie:accessToken` producer, and `correlate/decide.py` generates a header
regex. The old `Set-Cookie:\s*accessToken=([^;]+)` expression allows CR/LF inside
the value. Without a semicolon, it crosses into the following Set-Cookie header:
the expected 360-character token becomes a 746-character match.

`validate/extractors.py` rejects that match. Its header approximation also
duplicates parsed cookies after the actual wire headers. The emitter then omits
the rejected extractor and excludes the value from substitution. Request 2
retains the recorded Bearer token. The previously observed replay was login 200,
profile 401. Manual-review reporting did not prevent execution with stale state.

## Scoped fix

The shared cookie expression models RFC 6265 cookie-octets, optional quoted
wire values, a case-insensitive header name and a case-sensitive cookie name.
It anchors on a Set-Cookie header line, stops at attributes or the line boundary,
and cannot consume whitespace, CR/LF, another header or another cookie.
Verification and emission use the same grammar. Parsed cookies are a fallback
only when actual Set-Cookie headers are absent. The expression is compatible
with JMeter 5.6.3's Apache ORO regex engine.

Already accepted authentication dependencies always substitute runtime variables.
Their producer resets thread-local `vars` before extraction and asserts that fresh
values exist afterward. Extraction failure marks that sample failed and stops
that thread. An unverifiable extractor remains omitted and reported for review;
the plan cannot fall back to the recorded credential. Sentinel declarations
contain no captured authentication values.

Cookie-only sessions continue through JMeter's existing per-thread CookieManager.
Explicit cookie-to-header dependencies use an extractor. Percent-encoded cookies
are decoded only when the existing normalized dependency requires it, preserving
literal plus characters; exact encoded consumer slots are re-encoded at runtime.
JSON, header, CSRF, OAuth code/Location, challenge and refresh extractors retain
their existing discovery and matching behavior. No shared JMeter properties are
used for authentication state.

## Before/after evidence

The 76-workflow/39-application corpus was rerun from its original raw HARs.
An additional 74 existing HARs include real captures and synthetic fixtures;
they are reported separately and are not counted as new real workflows.

| Metric | Before | After |
|---|---:|---:|
| Frozen real workflows converted | 76/76 | 76/76 |
| Additional existing HARs converted | 74/74 | 74/74 |
| Crashes | 0 | 0 |
| Accepted auth dependencies verified, real corpus | 1/2 | 2/2 |
| Accepted auth dependencies materialized, real corpus | 1/2 | 2/2 |
| Hardcoded accepted auth dependencies, real corpus | 1 | 0 |
| Accepted auth dependencies materialized, existing corpus | 36/36 | 36/36 |
| Dead extractors, both corpora | 0 | 0 |
| New discovery/classification regressions | — | 0 |
| Confirmed false correlations, frozen real corpus | 3 | 3 |
| Newly introduced false correlations | — | 0 |
| DummyJSON observed profile HTTP status | 401 | 200 |

The JMX audit inspects producer subtree ownership, extractor variable names,
actual downstream request properties and raw/encoded/decoded literals. All
38 accepted auth dependencies materialize after the fix. Only DummyJSON's JMX
changes among the 76 new real workflows. All correlation identities, request
classifications, transactions and parameterization results match the pre-change
snapshot across all 150 HARs. The snapshot's file hashes remain unchanged.

The three confirmed false correlations are existing out-of-scope defects. The
requested absolute zero-false-correlation gate is therefore not met; this task
introduces zero new false correlations. Legacy non-auth unresolved dependencies
remain for their separate fixes. This result is not a production-readiness claim
for the entire converter or for authentication patterns absent from the corpus.

The actual DummyJSON capture obtains credentials from request 0's response;
its existing parameterization result still lacks username/password columns.
P1-1 preserves that result as instructed. Credential parameterization is proven
by the direct-login regression cases, not claimed fixed for this response-origin
workflow; its test-data policy remains a separate issue.

## Tests and replay

20 new generated-JMX cases cover semicolon/no-semicolon cookies; LF/CRLF and
multiple Set-Cookie headers; attributes including Expires; header/name casing;
quoted and encoded values; access/refresh chains; session CookieManager;
CSRF/custom headers; OAuth Location/code exchange; synthetic MFA; stale-token
removal; failed validation; unused/superseded tokens; credentials/OTP preservation;
thread-local variable scope; and preserving pagination-token behavior. Existing
tests are unchanged by this commit.

The working checkout passes 367 pytest tests. The isolated HEAD plus P1-only
commit passes 343 tests, including examples. These are the tests actually
available here; the stated 539-test suite was not present in this checkout.
Lint passes for all three new Python files.

Live JMeter 5.6.3 replay of the permitted DummyJSON sandbox generated plan gives
GET /users/1 200, POST /auth/login 200, GET /auth/me 200 and POST /auth/refresh 200.
Both recorded token literals are absent from the generated plan. This is a
single-user smoke replay, not a public-service load test.

A separately labeled local synthetic HTTP environment validates two VUs over
two iterations: four distinct logins, independent session/token ownership,
refresh consumption and 16 successful HTTP samples. A deliberately unverifiable
extractor replay fails the login assertion and sends zero downstream requests.
No real MFA replay was performed; MFA coverage here is synthetic mechanics.

Workspace evidence is retained in `p1-authentication/`: `FREEZE.json`,
`before.json`, `after.json`, `CORPUS_REGRESSION.json`,
`before-materialization.json`, `after-materialization.json`,
`MATERIALIZATION_SUMMARY.json`, `pytest-final.xml`, `pytest-commit.xml`, and
the `replay-dummyjson`, `replay-local`, `replay-local-unresolved` folders containing
generated JMX, JTL and JMeter logs. HARs and captured authentication values are
kept out of the source commit.
