# Supported Patterns & Known Limits

What `har2jmx` accommodates when turning a HAR into a production-ready JMeter plan, and the few
things no HAR-based tool can infer. Every row below is backed by a regression test and by the
cross-application dry-run gate (`tests/test_dryrun.py`) that validates every generated plan.

## Design principle

Decisions are **behavioural, not name-based**. A value is correlated or parameterized by *where it is
born and how it flows*, never by a dictionary of field names. This is why the tool works on
applications — and naming conventions — it has never seen: `productId`, `product_id`, `ProductID`,
`prodId`, `sku` are all matched by the same value, and the correlate-vs-parameterize choice runs on
lifecycle evidence.

## Correlation — every place a dynamic value can hide

A value is **correlated** (extracted at run time) when it is server-issued this run and consumed by a
later request. Detected across:

| Location | Example values | Extractor emitted |
|---|---|---|
| Set-Cookie / request cookie | session ids (`JSESSIONID`, `SPSESSION`) | Cookie Manager (auto-replay) |
| Response JSON body | tokens, created object ids (`orderId`, `bookingid`, `appointmentId`), continuation tokens | JSON extractor (`$..field`) |
| `Authorization: Bearer <token>` | JWT / OAuth access tokens | JSON + header substitution (`Bearer ${token}`) |
| HTML hidden inputs | CSRF, `__RequestVerificationToken`, `__VIEWSTATE`, `EventValidation`, `SAMLResponse` | Regex over the page |
| XML / SOAP envelope | `SessionId`, object ids returned in a SOAP response | Regex over the response |
| 302 `Location` redirect | OAuth authorization `code`, SAML `SAMLRequest`/`RelayState` | Header regex; producer set to **not follow redirects** |
| Response headers | `ETag` / version-lock tokens (replayed as `If-Match`) | Header regex |
| **Pagination / continuation cursors** | `nextCursor`, `next_page_token`, `continuationToken`, `scroll_id` | JSON/Regex — re-extracted per page, fed to the next request's cursor param |
| **Rotating CSRF tokens** | a double-submit token that changes on every response | re-extracted each step (`csrf`, `csrf2`, …) |
| **Per-user resource ids** returned by a session-scoped list | `accountId` from `/customers/${cif}/accounts`, `orderId` from `/users/${uid}/orders` | JSON extractor — see below |

**User-owned vs shared data.** An id returned by a GET and reused is normally existing master data
(parameterized from a CSV of known records, which spreads load across the catalog). But when the
producing request is itself **scoped by a per-session value** — its path/query carries a correlated
id such as `${cif}` — the records it returns belong to whoever logged in. A static CSV id then fits
only one login and 404s for every other user, so those ids are **correlated per user** instead. A
shared catalog (`/products`, `/doctors`) has no session id in its producer scope and is left as a
CSV parameter, preserving load-spread. The distinction is structural, not name-based.

Guarantees: variable names are **globally unique** (a generic `id` from two entities becomes
`orderId` / `shipmentId`, never a shared `${id}` that clobbers itself); correlations never ship the
literal value; extractors are structured-first (JSON > XPath/regex); and every extractor is paired
with a **correlation-health assertion** — a variable-scoped assertion that fails the sample if the
extractor fell back to its `NOT_FOUND_<var>` sentinel, so a broken correlation surfaces as a real
failure instead of a false-green (an app that returns HTTP 200 with an error body still 200s).

## Parameterization — entity-centric test data

A value is **parameterized** when it is user input or existing master data that varies per user.
Grouped into **entity-centric CSV datasets** (not one file per field), with related fields kept
row-aligned. Lifecycle rules:

- Existed before the run (returned by a GET/search, or client-supplied) → parameter.
- Created during the run (POST/201, then reused) → correlation, never a CSV value.
- Ambiguous / no evidence → flagged for review, never silently wired.

**One file per varying dataset, not per field.** A CSV earns its own file only when it has more than
one row — the only case where threads read different values. Every single-row dataset (which would
feed all users the same value) is merged into one row-per-user `TestData` set, so a small flow emits
one test-data file instead of six. One row is one virtual user's complete data; add rows to add
users. Datasets that genuinely vary per thread keep their own file.

**CSV row synthesis** grows datasets toward the thread count so N users exercise distinct data:

- Safe business data (names, amounts, prices, dates, quantities, free text, emails) is **varied**.
- Credentials (username/password/otp/pin/cvv/card) are **never fabricated** — kept as observed.
- Coded real ids (GUIDs, `PROD-…`, `ACC-…`) are **never fabricated** — cycled, kept valid.
- Client-generated per-request keys (idempotency / request-id / correlation-id UUIDs) become
  JMeter `${__UUID()}` — a fresh value per request, so 100 users never collide.

## Transaction names — stakeholder-readable

Named from endpoint semantics (REST path, GraphQL operation, or SOAPAction) — no app-specific tables:
`Launch Application`, `Login`, `Logout`, `View Patients`, `Open Patient`, `Customer Search`,
`Create Order`, `Update Booking`, `Checkout`, `Payment`, `View Receipt`, `Upload Document`,
`Initiate Transfer`, `Confirm Transfer`, `Generate Report`. IDs never leak into names; the landing
page reads as `Launch Application`; supporting XHRs nest inside their user action.

## JMeter constituents — a complete, runnable plan

Every plan contains: Test Plan + `THREADS`/`LOOPS`/`RAMP` variables · Thread Group (`${THREADS}`) ·
HTTP Request Defaults · **HTTP Cookie Manager** · **global HTTP Header Manager** (shared headers
hoisted once) · per-sampler Header Managers (request-specific only) · **Response Assertion** (2xx/3xx,
thread-group scope) · **correlation-health assertions** (one per extractor, fail on unresolved
correlation) · **Uniform Random Timer** (think time) · CSV Data Sets · Transaction Controllers ·
HTTP Samplers · JSON/Regex extractors (each with a `NOT_FOUND_<var>` default) · **multipart
file-upload** elements where applicable.

## Token refresh (OAuth2 `refresh_token` grant)

A capture that renews an expired access token mid-flow is handled end to end:

- The **login-issued** access token keeps the clean base name (`access_token`); the **refreshed**
  token is suffixed (`access_token2`). Calls before the refresh carry `${access_token}`, calls after
  it carry `${access_token2}` — each extracted from the response that actually issued it.
- The `refresh_token` is correlated from the login response and replayed in the refresh request body.
- A token refresh is recognized **structurally** (`grant_type=refresh_token`, not by endpoint name),
  so it is treated as background machinery: it never hijacks the surrounding user action's name (the
  action stays `View Orders`, not `Login`).
- The recorded **expiry failure** (the `401`/`403` on the stale token, immediately followed by a
  refresh and a successful retry of the same endpoint) is dropped, so the load script carries no
  built-in failure — its successful retry represents the real call.

## Verified across domains

Correlation/parameterization correctness and a clean dry-run were verified on real or representative
captures spanning: travel/hospitality, e-commerce/retail, content/publishing, pet-retail/logistics,
community, media (GraphQL), ERP (SOAP), identity (OAuth2 + SAML), healthcare/HIS, banking/fund
transfer, insurance claims (multipart upload), and government-style server-rendered CSRF/ViewState —
plus large day-to-day flows (login → explore → select → checkout → payment) at 100 users.

## Known limits (need hand-written JMeter, not inferrable from a HAR)

- **OAuth 2.0 PKCE** — `code_verifier` / `code_challenge` are client-side crypto; JMeter must compute
  them (JSR223), no recorder can recover the verifier.
- **HMAC / signed requests** — a request signature derived from body + timestamp + a client secret
  must be recomputed in JMeter; the secret isn't in the HAR.
- **One-time secrets** — real OTPs and live logins can't be synthesized; the tool generates the CSV
  structure and flags that you supply real data for N users.
- **WebSocket / gRPC** — detected and reported, but scripting needs JMeter plugins.
- **Unscheduled token re-auth** — the *recorded* refresh is scripted (above). But a token expiring at
  an unpredictable moment during a long soak needs a conditional "on 401 → refresh → retry" loop
  (`If Controller` + JSR223), which is dynamic control flow no linear HAR expresses.

## Running & validating

```bash
pip install -e .          # or: PYTHONPATH=src python -m har2jmx
har2jmx                    # web UI at http://127.0.0.1:8000 — upload a HAR, download the bundle
```

Programmatic: `har2jmx.engine.analyze(har_bytes)` → `EngineResult`; `emit_jmx(result, out, config)` →
`.jmx` + CSVs; `validate_plan(result, xml)` → list of issues (empty means production-clean).
