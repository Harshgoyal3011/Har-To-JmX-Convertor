# Architecture Redesign — HAR → Enterprise JMeter

**Status:** design only. No core behavior is changed by this document.
**Companion:** [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md) (milestones, file changes, tests).
**Audit basis:** the full codebase (see [`ARCHITECTURE.md`](ARCHITECTURE.md) and the Phase-1 context map) plus a
defect analysis of the current engine's output on a real enterprise capture. **The engine must stay
application-agnostic** — no capture is treated as a reference to tune toward. Sample output is used
only to surface *general* failure patterns; detectors are evidence/heuristic-based, never hardcoded
to any app, vendor, or domain, and are validated across multiple app types.

---

## 1. Current architecture (as audited)

**Entry:** `server/handler.py` → `pipeline_v2.convert_har_v2(upload, config)`.

**Data flow today:**
```
HAR bytes
  → har/reader + har/samplers   parse, filter statics, group transactions → ScriptIR
  → ir/compat                   ScriptIR flattened straight back to list[SamplerModel]   ← IR is bypassed
  → correlations/discover_enhanced   inventory response values, keep any reused later
  → analyzer/dependency_graph        producer→consumer graph
  → analyzer/value_origin            re-scans everything; builds value_map
  → parameters/discover_enhanced     business-input discovery
  → correlations/reclassify          promote "existing entity" IDs to parameters
  → parameters/entities              cluster params → CSV files
  → validation/rules8,9 + quality_gate   checks + auto-corrections
  → analyzer/review                  heuristic score (mislabeled "AI")
  → jmx/builder                      emit .jmx
  → reports/builders                 markdown + summary.json
```

**Core data model:** `SamplerModel` (one HTTP exchange) is the working unit; `CorrelationRule`,
`Parameter`, `DataEntity`, `BuildResult` are the outputs. `models.py`.

### Current algorithms (the ones producing poor results)

- **Transaction discovery** (`har/samplers.py`): pageref grouping + a large regex table
  (`BUSINESS_TRANSACTION_RULES`) + time-gap heuristics. Reasonable idea, but falls back to the
  last path segment and has no concept of "supporting calls belong to the parent action."
- **Correlation** (`correlations/discover.py` + `discover_enhanced.py`): inventory every value in
  a response, then keep it if `_find_consumers` finds the **same string anywhere** in any later
  request's body/headers/path. Confidence from source type. **This is the main defect source.**
- **Parameterization** (`parameters/discover_enhanced.py`): scan requests for values whose *name*
  matches `USER_DATA_RE`; broad keyword net. `reclassify.py` promotes response IDs from GET/list
  endpoints to parameters and drags in every sibling field.
- **CSV** (`parameters/entities.py`): union-find clustering by shared sampler → one CSV per cluster;
  fabricates extra rows. No "is this dataset actually needed" gate.
- **JMX** (`jmx/builder.py`): solid emitter; one Transaction Controller per `transaction` value.

---

## 2. Root causes of the current defects (evidence-based)

Diagnosed from the current engine's output on a real enterprise capture — these are **general**
failure patterns of the algorithms, not tied to any one application:

| # | Defect (observed) | Root cause | Where |
|---|---|---|---|
| R1 | RUM/telemetry beacons (`mob_dl`, `ak_*`, `mem_lssz`, `t_page`) correlated | Beacons are POSTs, so `is_application_request` keeps them; no telemetry classifier | `har/filter.py` |
| R2 | Static `.svg`/`.json` act as correlation producers & consumers | Filter is binary keep/drop; kept requests fully participate in correlation | `har/filter.py`, `correlations/` |
| R3 | List responses explode (`submenuId`×22, `bedStatusId`×9) | Each array element's id becomes a separate rule; dedup keys on (var,value) so distinct values survive | `correlations/discover.py` |
| R4 | "+321 consumers" incl. static fetches; `bedStatusId` "consumed by /connect/token" | `_find_consumers` = loose substring match anywhere; short/numeric values collide | `correlations/discover.py` |
| R5 | Static reference-data JSON (lookup/master tables served as files) becomes CSV "business entity" | `classify_producer_as_existing_entity` returns True for any GET+JSON+id | `correlations/reclassify.py` |
| R6 | 157 params / 20 CSVs; placeholders (`"string"`, `"Address"`) captured | Name-keyword net + sibling-field dragging; no value-quality gate; no dataset-need gate | `parameters/`, `entities.py` |
| R7 | Misclassification (`bedStatusId` = "Security Identifier") | Classification from shallow name/shape rules, not lifecycle/evidence | `correlations/discover.py:classify_identifier` |

**The unifying flaw:** the engine reasons on **string coincidence and field-name shape**, and treats
every kept request as business-relevant. It has no model of *noise*, *value lifecycle*
(existed-before vs created-during), or *semantic position*. That is what we redesign.

---

## 3. Target architecture — an IR-centric staged reasoning pipeline

Make the **Intermediate Representation the spine** (today it is built then discarded). Every stage
consumes the IR and *annotates* it; no stage re-parses the HAR. Each stage is pure, independently
testable, and adds evidence rather than mutating shared globals.

```
HAR ─▶ [P1] Normalize ─▶ IR (requests, responses, context)
        [P2] Noise/Request classification      → each request tagged: static|telemetry|auth|business|poll|upload|download
        [P3] Application & auth understanding   → app style + auth mechanism (evidence-gated)
        [P4] Workflow discovery                 → user actions (transactions) w/ supporting calls nested
        [P5] Entity discovery                   → business entities + attributes
        [P6] Entity relationships               → parent/child links (keep rows aligned)
        [P7] Value lineage / dependency graph   → producer→value→consumers, position-aware, transform-aware
        [P8] Value classification engine        → STATIC | BUSINESS_MASTER_DATA | RUNTIME_GENERATED | UNKNOWN
        [P9]  Correlation decision  ─┐
        [P10] Parameterization dec. ─┴─ driven by P8 class + lifecycle, never by name/shape alone
        [P12/13] Entity-centric CSV + optimizer → few meaningful datasets, need-gated
        [P14] Extractor strategy                → structured first (JSON/XPath/CSS) then boundary then regex
        [P15] Replay validation                 → static multi-iteration analysis; auto-repair high-confidence only
        [P16] JMX quality review                → strip noise, dedupe, verify
        [P17/18] Metrics + reports              → precision/coverage measured, not fabricated
```

### The central reframe (fixes R3–R7)

**1. Classification before decision.** A value is never correlated or parameterized directly. It is
first classified with evidence:

- `STATIC` — same across runs, not runtime state → leave hardcoded.
- `BUSINESS_MASTER_DATA` — existed **before** this execution (returned by a GET/list/read, or sent in
  a request with no prior producing response) → **parameterize** (entity-centric).
- `RUNTIME_GENERATED_DATA` — **created during** this execution (returned by a create/POST→201, or a
  session/token/CSRF/OAuth artifact) and consumed later → **correlate**.
- `UNKNOWN` — insufficient evidence → **flag for manual review**, never silently auto-wire.

**2. Lifecycle discriminator (fixes the "itemId vs orderId" problem, Phase 11).**
```
Was the value present in a REQUEST before any RESPONSE produced it?      → master data (parameterize)
Was it first seen in a create response (POST/PUT → 201/200-create)?      → runtime (correlate)
Was it first seen in a read/list response and later sent as-is?          → master data (parameterize the whole record)
```

**3. Position-aware, transform-aware lineage (fixes R4).** A "consumer" requires the value in a
*meaningful slot* — a header value, a JSON/form field value, a query value, or a full path segment —
with a minimum specificity (length/entropy) so `"67"` doesn't match 300 requests. Recognize
equivalence across `12345` / `"12345"` / `/patient/12345` where evidence supports it, instead of raw
substring scanning.

**4. Noise is a first-class tag (fixes R1, R2).** Telemetry/RUM/beacon and static assets are
classified, reported in an **Excluded Requests** section, and excluded from lineage/correlation —
but retained in the IR (not deleted) so decisions stay auditable.

---

## 4. Target module map

New or reshaped modules (proposed homes under `src/har2jmx/`):

| Stage | Module (new*/existing) | Responsibility |
|---|---|---|
| P1 | `ir/models.py`, `ir/build.py`* | Rich IR from HAR; the single source all stages read |
| P2 | `classify/request_noise.py`* | Tag each request static/telemetry/auth/business/… |
| P3 | `understand/application.py`*, `understand/auth.py`* | App style + auth mechanism (evidence-gated) |
| P4 | `workflow/transactions.py`* (absorbs `har/samplers` grouping) | User-action transactions w/ nested support calls |
| P5–P6 | `entities/discovery.py`*, `entities/relationships.py`* | Entities, attributes, parent/child graph |
| P7 | `lineage/graph.py`* (absorbs `analyzer/dependency_graph`) | Position/transform-aware value flow |
| P8 | `classify/value_engine.py`* (absorbs `analyzer/value_origin`) | 4-class value classification w/ evidence |
| P9 | `correlate/decide.py` (reshapes `correlations/`) | Correlation from P8, lifecycle-driven |
| P10–P13 | `parameterize/decide.py`, `parameterize/csv.py` (reshapes `parameters/`) | Entity-centric params + CSV optimizer |
| P14 | `emit/extractors.py` (from `jmx/builder`) | Structured-first extractor selection |
| P15 | `validate/replay.py` (reshapes `validation/`) | Multi-iteration static validation + auto-repair |
| P16 | `emit/review.py` | Final PE review pass on the plan |
| P17–P18 | `reports/metrics.py`*, `reports/builders.py` | Measured metrics + customer reports |

`*` = new. Existing `discover.py`/`discover_enhanced.py` twins and dead `pipeline.py` are retired as
their logic moves into the staged modules.

---

## 5. Migration approach — strangler, not big-bang

The prompt's rule "preserve working functionality unless intentionally replaced" drives this:

1. **Build the new pipeline beside the old one.** `pipeline_v2.convert_har_v2` stays the live path
   until the new staged pipeline reaches parity on the real HAR.
2. **Golden-file safety net first** (see plan): snapshot current JMX output so every milestone proves
   what changed and that nothing *unintended* changed.
3. **One milestone at a time**, each behind tests, each compared on real-HAR metrics before proceeding.
4. **Cut over per stage**: as each new stage lands and beats the old on precision, route the live
   pipeline through it; delete the superseded code only after cutover.

**Hard dependency:** stages P7–P18 are *measured*, not guessed. We need representative real captures
in `examples/` — **ideally 2–3 spanning different app types/domains** so detectors are validated for
generality rather than tuned to any single app — to make "less rubbish" a number, not an opinion.
Milestones 1–2 (IR + noise) can begin without them; accuracy milestones cannot be signed off without
them.
