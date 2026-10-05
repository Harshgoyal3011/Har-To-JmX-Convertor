# Architecture

`har2jmx` turns a browser HAR into a JMeter plan. Decisions are **behavioural** (producer → consumer,
lifecycle, replay necessity), never field-name blacklists or app-specific tables.

The 12-stage reasoning pipeline is the live product. There is no second converter (`pipeline_v2` and
the old `correlations/` / `parameters/` / `analyzer/` trees are gone).

## Adapters vs core

```
HAR bytes ──▶ engine.analyze() ──▶ EngineResult ──▶ emit_jmx() ──▶ .jmx + CSV + reports
                    ▲                                      ▲
                    │                                      │
              no I/O, no HTTP                    writes generated/
                    │
         ┌──────────┴──────────┐
         │  har2jmx (web UI)   │  stdlib HTTP server + static/
         └─────────────────────┘
```

- **`analyze(har)`** (`engine.py`) — pure: parse, reason, return decisions and measured metrics.
- **`emit_jmx(result, …)`** (`emit/jmx.py`) — materialize a runnable JMeter 5.x plan.
- **`server/handler.py`** — upload HAR, call analyze + emit, zip the bundle, return a UI summary.
- **`webreport.py`** — JSON the browser renders. Required-correlation rows are filtered to extractors
  that actually exist in the generated JMX (JMX is the source of truth).

Entry point: `python -m har2jmx` / `har2jmx` → `har2jmx.__main__:main` → `server.handler.main`
(default `http://127.0.0.1:8000`).

## Reasoning pipeline

```
HAR
  → M1  IR (normalized capture)
  → M2  request-role / noise tags
  → M3  application + auth profile (evidence only)
  → M4  transactions (user actions)
  → M5–M6  entities + relationships
  → M7  lineage (producer → value → consumers)
  → M8  value class (STATIC / MASTER / RUNTIME / UNKNOWN)
  →     discover correlation CANDIDATES   (high recall — do not thin here)
  →     necessity GATE                    (required vs rejected)
  → M9  REQUIRED correlations only
  → M10 parameterization (+ intent)
  → M11 replay validator + extractor verify
  → M12 metrics on EngineResult
  → emit JMX
  → UI audit (must match extractors in XML)
```

Discovery must **not** jump straight to “final correlation.” A candidate is required only when
provenance, lifecycle, downstream use, and replay necessity all agree.

### Correlation gate (after discovery)

A candidate is **emitted** only if it is server-generated, consumed later, session/transaction/entity
scoped, and hardcoding the recorded value would break another VU. Otherwise it is classified, not
wired:

| Kind | Meaning |
|------|---------|
| `CONFIGURATION` | Environment / SETTINGS / static URLs and ids |
| `PROTOCOL_METADATA` | OIDC/OAuth capability arrays, well-known vocab |
| `MASTER_DATA` | Existing catalog/selected records (CSV/hardcode policy, not extract) |
| `NO_CONSUMER` | No downstream use — never emit a dead extractor |
| `SUPERSEDED` | Covered by a longer runtime variable |
| `REVIEW` / `NOT_REQUIRED` | Insufficient or not needed for replay |

Created-this-run entity ids (POST/PUT/PATCH) can correlate; GET/search selected records follow the
master-data / parameter policy. Same field name can be either, depending on evidence.

The UI reports **candidates vs required vs rejection counts**, and the **Correlations** panel lists
only required/emitted variables.

## What each module does

| Path | Role |
|------|------|
| **`har/reader.py`** | Parse HAR JSON: headers, cookies, post bodies, response text. Shared primitives only. |
| **`ir/normalized.py`** | Dataclasses: capture, request/response, typed body (JSON/form/multipart/GraphQL/SOAP/XML). |
| **`ir/build.py`** | HAR → `NormalizedCapture`. Keeps every entry; later stages tag, they do not drop here. |
| **`classify/request_noise.py`** | Role + exclude: static, telemetry/RUM vendors, CORS, vs auth/business. Auth is kept. |
| **`classify/content_role.py`** | Parsed response contracts and HTTP role evidence for business data on static-looking paths. |
| **`understand/application.py`** | API style / SPA / stack from HAR evidence, not assumed product names. |
| **`understand/auth.py`** | Cookie, bearer, form login, refresh, SAML/OAuth traces when present. |
| **`understand/models.py`** | `Detection` / `EvidenceBag` shared by understanders. |
| **`workflow/transactions.py`** | Group into user actions (navigation + think-time). Supporting calls nest; names from the anchor request. |
| **`entities/discovery.py`** | Business entities and attributes from payload/URL structure. |
| **`entities/relationships.py`** | Parent/child, aligned instance rows for CSV. |
| **`lineage/graph.py`** | Whole-slot matching (not substring) + transform-aware equality. |
| **`classify/value_engine.py`** | Lifecycle: existed-before vs created-this-run vs user input → `ValueClass`. UNKNOWN is never auto-wired. |
| **`classify/lifecycle.py`** | Resolve GraphQL operations and separate schema/catalog reads from runtime creation. |
| **`correlate/decide.py`** | High-recall **candidate** discovery and extractor choice (JSON, regex, Cookie Manager). |
| **`correlate/necessity.py`** | Gate: required vs configuration / protocol / master / superseded / no consumer. |
| **`correlate/cookies.py`** | Shared bounded Set-Cookie grammar for extraction and verification. |
| **`parameterize/intent.py`** | Would a PE vary this as test data? User input / selected existing → CSV; config and runtime state do not. |
| **`parameterize/context.py`** | Request occurrences and payload context used to approve individual test-input slots. |
| **`parameterize/decide.py`** | Entity-centric datasets, need-gated columns, aligned rows. |
| **`validate/replay.py`** | Static multi-VU checks (order, missing runtime, CSV vs correlate conflicts). Honors the necessity audit. |
| **`validate/extractors.py`** | Does each extractor uniquely hit the producer response? Refine or flag. |
| **`engine.py`** | Orchestrates M1–M11, attaches metrics (`EngineResult`). |
| **`emit/jmx.py`** | Thread group, Cookie Manager, CSV Data Sets, transactions, samplers, extractors, whole-slot `${var}`. |
| **`emit/authentication.py`** | Reset thread-local authentication state and stop a thread when required fresh extraction fails. |
| **`emit/redirects.py`** | Assign observed redirect chains to following or explicit runtime Location execution. |
| **`emit/validate.py`** | Dry-run XML: constituents, unused extractors/CSV columns, unresolved variables. |
| **`webreport.py`** | UI payload; correlation list ∩ JMX extractor names. |
| **`server/handler.py`** | HTTP routes, upload limits, result prune, zip downloads. |
| **`server/multipart.py`** | Multipart parse for HAR upload (stdlib). |
| **`static/`** | Console UI (`index.html`, `app.js`, `styles.css`). |
| **`patterns.py`** | Shared regexes (GUID, hidden input, token-ish names, static extensions) — structural, not app catalogs. |
| **`utils.py`** | Safe JMeter variable names. |
| **`paths.py`** | Package root and `generated/` output directory. |

Tests live in `tests/` (fixtures + example HARs). Runtime output is `generated/` (git-ignored except `.gitkeep`).

## Parameterization vs correlation

| | Correlate | Parameterize | Hardcode |
|--|-----------|--------------|----------|
| **When** | Server issued this run, consumed later, needed for another session | User-typed or user-selected existing data | Config, protocol metadata, unused master |
| **JMX** | Extractor + `${var}`, literal gone | CSV Data Set + `${col}` | Recorded literal |

Intent (`parameterize/intent.py`) does not rewrite lineage or candidate discovery.

## Authentication and redirect execution

Set-Cookie extraction stops at cookie attributes and header line boundaries.
Verification uses the same grammar, with parsed cookies as a fallback only when
wire headers are absent. Cookie-only sessions use JMeter's per-thread Cookie
Manager; accepted cookie-to-header dependencies use explicit extraction.

Accepted authentication dependencies use runtime variables even when extractor
verification fails. Their producers reset thread-local values before extraction
and stop the thread if fresh state is missing. Unverifiable extractors are
reported for manual review without replaying the captured credential.

Observed redirect targets have one execution owner. Consecutive GET/HEAD chains
with compatible origin, transaction, headers and bindings can use JMeter
following; the separately captured target samplers are then omitted. Chains
requiring explicit execution disable following and use accepted Location
correlations or a whole-Location extractor with runtime URI resolution. Missing
required Location state fails the producer and stops that thread.

## Lifecycle and request retention

GraphQL operation evidence takes precedence over HTTP POST as a creation signal.
Schema reads are configuration; catalog/entity reads describe existing data.
Read-issued credentials and pagination handles retain runtime ownership.
Unresolved read lifecycles remain UNKNOWN for review.

Static-looking paths can contain business data. Parsed resource catalogs and
record collections can establish an API role, while singleton or XML records
need additional request evidence. Rendering and telemetry evidence takes
precedence; HTML, SVG, malformed bodies and flat bootstrap configuration do not
qualify merely because their content is structured.

## Layout

```
src/har2jmx/     package (stdlib only)
tests/           pytest
examples/        sample HARs
docs/            architecture, supported patterns, parameterization and deployment
generated/       conversion output
```

Capability matrix (locations, extractors, known limits): [SUPPORTED_PATTERNS.md](SUPPORTED_PATTERNS.md).
Test-input decisions and approved CSV substitutions: [PARAMETERIZATION.md](PARAMETERIZATION.md).
