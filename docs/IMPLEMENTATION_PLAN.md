# Implementation Plan — HAR → Enterprise JMeter

Companion to [`ARCHITECTURE_REDESIGN.md`](ARCHITECTURE_REDESIGN.md). Progressive, one milestone at a
time. **Rule for every milestone:** run existing checks, add new tests, compare metrics on real HARs,
and do not proceed on a regression.

## Ground rules

- **Strangler migration.** The live path (`pipeline_v2.convert_har_v2`) keeps working until the new
  staged pipeline reaches parity. New modules are additive first, cut over per stage.
- **Regression net (Milestone 0.5, before any accuracy change).** A golden-file test snapshots the
  current generated `.jmx`/reports for a fixed HAR so unintended output changes are caught. Timestamp
  and `result_id` normalized.
- **Measurement.** Accuracy milestones (M7+) are validated against **real HARs in `examples/`**. Until
  a real capture is supplied, those milestones can be *built* but not *signed off*.

## Milestones

| M | Name | Key files (new*/changed) | New tests | Exit criteria |
|---|---|---|---|---|
| **1** | **IR + parser normalization** | `ir/normalized.py`*, `ir/build.py`* (reuse `har/reader.py` primitives) | `tests/test_ir_build.py` | Rich IR builds from HAR; request/response/context fields populated; body type (json/form/multipart/graphql/soap/xml) detected. Live path untouched. |
| 0.5 | Golden regression net | `tests/test_golden_jmx.py`* + `tests/fixtures/` | golden test | Current JMX for a fixed HAR is snapshotted and locked. |
| 2 | Request noise classification | `classify/request_noise.py`* | `tests/test_request_noise.py` | Each request tagged static/telemetry/auth/business/poll/upload/download using **general vendor + shape patterns** (known RUM/telemetry vendors — Akamai mPulse/boomerang, GA, Adobe, Dynatrace, AppDynamics…; static extensions/paths), tagged not deleted. `RequestClassificationReport`. |
| 3 | Application & auth understanding | `understand/application.py`*, `understand/auth.py`* | tests | App style + auth mechanism detected **only** with HAR evidence. |
| 4 | Workflow / transaction discovery | `workflow/transactions.py`* | tests | Transactions = user actions; supporting calls nested; no per-API inflation; business-meaningful names. |
| 5 | Business entity discovery | `entities/discovery.py`* | tests | Entities + attributes grouped from payload/URL/response structure. |
| 6 | Entity relationships | `entities/relationships.py`* | tests | Parent/child links; related values stay row-aligned. |
| 7 | Value lineage / dependency graph | `lineage/graph.py`* | tests | Producer→value→consumers, position- & transform-aware; short/numeric values don't over-match. |
| 8 | Value classification engine | `classify/value_engine.py`* | tests | Every value → STATIC / BUSINESS_MASTER_DATA / RUNTIME_GENERATED / UNKNOWN, with reason+confidence; UNKNOWN never auto-wired. |
| 9 | Lifecycle-aware correlation | `correlate/decide.py` | tests | Correlate only runtime-generated+consumed values; existing-master IDs excluded. Precision up on real HAR. |
| 10 | Entity parameterization + CSV optimizer | `parameterize/decide.py`*, `parameterize/csv.py`* | tests | Entity-centric datasets; need-gated; placeholders/statics rejected; few meaningful CSVs. |
| 11 | Replay validator | `validate/replay.py` | tests | Multi-iteration static analysis; auto-repair high-confidence; flag ambiguous. |
| 12 | JMX optimization + final review + metrics | `emit/*`, `reports/metrics.py`* | tests | Noise stripped; structured extractors; measured metrics (coverage/precision), not fabricated. |

## Cutover

After M9–M10 beat the old engine on real-HAR precision, route `pipeline` through the staged modules
and retire `correlations/discover*.py`, `parameters/discover*.py`, dead `pipeline.py`, and the
immediate IR-flatten.

## Knowledge / inputs still needed

1. **Representative real HAR(s) in `examples/`** — one or more, **ideally 2–3 across different app
   types/domains** so detectors are validated for generality and nothing overfits (local, git-ignored).
   No single capture is a reference target. Blocks sign-off of M7–M12.
2. **Rough ground truth per capture** — 3–5 values that truly matter for replay, plus which traffic is
   noise (e.g. known RUM/telemetry vendors), so precision can be scored objectively.
3. **Target scope** — which app families to prioritize first (e.g. REST/JSON SPA, SAP, Salesforce,
   Guidewire, ServiceNow). No default is assumed; detectors stay evidence-based and app-agnostic.

## Status

- **M1 — normalized IR:** ✅ done (8 tests). Additive, no behavior change.
- **M2 — request noise classification:** ✅ done (8 tests). Tags roles + exclusion on the IR;
  `build_request_classification_report`. Additive, no behavior change.
- **M3 — application & auth understanding:** ✅ done (6 tests). Evidence-gated `ApplicationProfile`
  (API style / server stack / SPA / enterprise platform) + `AuthProfile` (mechanisms, token refresh,
  primary). Nothing claimed without evidence. Additive, no behavior change.
- **M0.5 — golden regression net:** recommended before the accuracy milestones (M9+) cut over.
- Everything else: designed, not started.
