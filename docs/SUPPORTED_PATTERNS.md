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

Guarantees: variable names are **globally unique** (a generic `id` from two entities becomes
`orderId` / `shipmentId`, never a shared `${id}` that clobbers itself); correlations never ship the
literal value; extractors are structured-first (JSON > XPath/regex).

## Parameterization — entity-centric test data

A value is **parameterized** when it is user input or existing master data that varies per user.
Grouped into **entity-centric CSV datasets** (not one file per field), with related fields kept
row-aligned. Lifecycle rules:

- Existed before the run (returned by a GET/search, or client-supplied) → parameter.
- Created during the run (POST/201, then reused) → correlation, never a CSV value.
- Ambiguous / no evidence → flagged for review, never silently wired.

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
hoisted once) · per-sampler Header Managers (request-specific only) · **Response Assertion** (2xx/3xx)
· **Uniform Random Timer** (think time) · CSV Data Sets · Transaction Controllers · HTTP Samplers ·
JSON/Regex extractors · **multipart file-upload** elements where applicable.

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

## Running & validating

```bash
pip install -e .          # or: PYTHONPATH=src python -m har2jmx
har2jmx                    # web UI at http://127.0.0.1:8000 — upload a HAR, download the bundle
```

Programmatic: `har2jmx.engine.analyze(har_bytes)` → `EngineResult`; `emit_jmx(result, out, config)` →
`.jmx` + CSVs; `validate_plan(result, xml)` → list of issues (empty means production-clean).
