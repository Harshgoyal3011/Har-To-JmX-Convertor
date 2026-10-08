# REAL100 independent baseline report

The unchanged engine converted all 100 newly recorded HARs and JMeter loaded every plan. Correctness and replay readiness remain materially below conversion success. This report contains measured assessed subsets; it does not claim complete independent ground truth or 100 replay-ready workflows.

The frozen corpus contains 31 native browser business workflows and 69 documented public API journeys across 55 applications. Historical application aliases, business origins, HAR hashes and business request sequences were excluded before admission. Raw HARs and UI/API action records are preserved. Four completed Vikunja operations have missing outbound bodies in the browser HAR and are capture-limited. Most API journeys are read/catalog flows. SOAP, GraphQL request bodies, file uploads and exhaustive retry/transformation scenarios were not exercised.

## Executive scorecard

| Measure | Result |
| --- | --- |
| Conversions | 100/100 |
| Applications | 55 |
| Confirmed meaningful input groups | 241 |
| Correctly parameterized / confirmed recall | 176/241 — 73.03% |
| Parameter precision | UNASSESSED; 61.79% confirmed-action lower bound |
| CSV columns / necessary confirmed | 280 / 173 |
| Unnecessary CSV columns | UNASSESSED; 103 unsupported by recorded explicit actions need review |
| Confirmed runtime edges in retained workload | 618 |
| Correct runtime edges / confirmed recall | 278/618 — 44.98% |
| Assessed correlation precision | 96.15%; 100 confirmed / 104 assessed, 145 accepted unassessed |
| Capture-resolution materialization | 70.68%; fresh runtime rate UNASSESSED |
| Confirmed false correlations | 4 |
| Dead extractors / undefined variables | 6 / 0 |
| R01 lost queries / R02 query-body crossings | 0 / 0 observed in 737 final samplers |
| JSON type failures | 8 |
| JSONPath syntax / wrong selected value | 1 / 3 |
| Replay-ready proven / manual repair | 0 / 56 |
| Ready with review / capture limited | 40 / 4 |
| Protected regressions / tests | 202/202 conversions; 533 tests passed |

## What the evidence proves

Source-only labels were frozen before the first converter run. Exact producer/consumer locations and original types remain in the truth CSVs. Equality only locates evidence candidates; ambiguous repeated issuers remain REVIEW. There are 241 confirmed input groups, 11 input occurrence rows requiring review and four capture-limited input rows. The source audit identifies 2,466 confirmed runtime edge observations; 618 consumers are retained in the generated workload. Excluded resource consumers are reported separately. Session/cookie edges are included; these totals must not be mistaken for created-business-object dependencies alone.

Parameter recall is for confirmed recorded input groups. A full precision figure is unavailable because default controls, implicit selections and all generated columns were not independently adjudicated. The 103 columns unsupported by explicit recorded actions cannot all be declared unnecessary. Correlation precision applies only to 104 evidenced accepted decisions. The other 145 remain unassessed. Four confirmed false correlations treat an existing Moodle recent-items catalog's module/name values as runtime state.

Final XML checks cover 737 samplers, CSV structure, references, extractor placement, URLs, bodies, headers, cookie declarations and redirect plans. JMeter's own SaveService loaded all 100 plans. Its JSONPath evaluator checked generated expressions against original responses. A JSONPath containing an unquoted space is invalid; three broad paths select a first array value different from the intended captured value. Eight numeric JSON scalars become strings across four workflows. These are known representation/identity/extraction issues, not repaired by this benchmark.

## Wire and replay evidence

Twenty generated workflows ran through a deterministic local receiver with one user and two iterations, preserving actual CSV files and generated processors. Destination and cookie scope were adapted for loopback. The receiver served captured responses; it did not issue fresh business IDs or establish independent live sessions. This is a smoke validation, not a load test or a live business replay.

The receiver observed 620 HTTP requests. JMeter recorded 738 samples including transaction parents, with 18 failures. Captured WebSocket upgrades, third-party redirect mapping, existing intermediate HTTP 422 responses and a local parser error account for smoke failures that require review; they are not automatically converter defects. Six query differences are encoding-only. Twenty further observations follow third-party redirect targets that add liSync=true, so exact HAR source mapping is limited. Ten body differences include numeric representation changes. R01/R02 ownership checks show zero query loss or query-to-form-body crossing; this does not erase those separate representation/redirect findings.

No workflow is marked REPLAY_READY from XML loading, captured-response replay or status assertions alone. Forty require review, 56 require manual repair from assessed defects, and four are capture-limited. Fresh-state and permitted live two-iteration replay remain unassessed.

## Systemic causes

- **parameter discovery**: 43 workflows; 65 findings. Source: `src/har2jmx/parameterize/intent.py; src/har2jmx/parameterize/decide.py`.
- **extractor generation**: 17 workflows; 56 findings. Source: `src/har2jmx/correlate/decide.py; src/har2jmx/validate/extractors.py`.
- **materialization**: 12 workflows; 23 findings. Source: `src/har2jmx/emit/jmx.py; src/har2jmx/correlate/decide.py`.
- **JSON/type serialization**: 4 workflows; 8 findings. Source: `src/har2jmx/emit/jmx.py`.
- **lifecycle classification**: 1 workflows; 4 findings. Source: `src/har2jmx/classify/lifecycle.py; src/har2jmx/classify/value_engine.py`.

The categories can overlap. Counts are observed affected workflows, not estimates of every latent failure. No new source root cause has been independently isolated; observed failures manifest already known parameter discovery, materialization, lifecycle/identity, numeric typing and JSONPath weaknesses.

The next engineering repair should establish occurrence-scoped semantic ownership and exact approved producer/consumer binding. It addresses a high-impact prerequisite for runtime correctness and independent input ownership. Parameter discovery has the largest observed workflow count, but increasing parameter or correlation counts would not resolve wrong ownership. Preserve the existing policies and validate each exact final consumer after the scoped repair.

## Regression protection

The protected 52 + 76 + 74 inputs were not modified. All 202 converted, decisions and CSV bytes matched accepted historical outputs, and sampler/transaction counts stayed unchanged. After normalizing timestamps and this benchmark's loop count, EX-073 alone differs in final JMX because the current engine already contains the accepted SAML consumer correction. The recorded R01 before/after audit is linked in the regression JSON. All 533 repository tests passed. Engine source and test hashes match the pre-collection freeze.

## Remaining work and limits

Exhaustive input/non-runtime ground truth, necessary-versus-unnecessary CSV adjudication, fresh runtime materialization, all identity collision scenarios and permitted live smoke replay are incomplete. Overall parameter precision, fresh runtime materialization rate and proven live replay readiness are therefore unassessed. Do not interpret zeros for undefined variables or R01/R02 ownership failures as evidence that lifecycle, identity, JSON numeric typing, JSONPath, extraction health or business replay defects are solved.

The requested fifteen deliverables and raw evidence are in this directory. Supplemental files include source hashes, the executive scorecard, natural occurrence inventory, JMeter expression results, wire observations, smoke logs and full pytest XML. No converter source changes were made.

## Concrete created-ID ownership failures

A supplemental exact source review confirms five workflows where server-created IDs receive CSV owners. This review preserves the frozen primary truth totals and is not folded into recall denominators. See `CREATED_RUNTIME_CSV_OWNERSHIP_EXAMPLES.json` for source responses and final expressions.

- Moodle: created course `id=5` is emitted as `${newsitems}`. The captured course ID and a separate news-items setting happen to be equal.
- eLabFTW: newly issued experiment ID is emitted as CSV `${id}`.
- OpenEMR: a save-response JavaScript redirect issues the patient ID, but the demographics consumer uses CSV `${set_pid}`.
- InvoiceShelf: newly created customer `data.id` is emitted as CSV `${customers}` in its stats request.
- Grocy: newly created chore ID is emitted as CSV `${chore_id}` in the next-assignment request.

These failures demonstrate why correct captured values and successful local response replay do not prove fresh runtime ownership. They reinforce occurrence-scoped semantic ownership and approved producer/consumer binding as the next repair.
