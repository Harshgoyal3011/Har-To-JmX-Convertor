# Correlation Engine — Pre-Change Analysis

**No code was changed for this document.** It answers, in order: what already works, where misses occur,
where over-correlation occurs, whether the architecture supports the required behaviour, and the
smallest safe change. Evidence is the 44-workflow real benchmark (`FINAL_BENCHMARK_REPORT.md`) plus a
new multi-run differential experiment run specifically for this analysis.

---

## 1. The pipeline, stage by stage

| # | Stage | Location |
|---|---|---|
| 1 | **Candidate discovery** | `lineage/graph.py` — `build_lineage:326`, `_request_slots:171`, `_response_slots:260`, `_walk_json:138`, `_augment_embedded:439` |
| 2 | **Classification** (provenance → role) | `classify/value_engine.py` — `classify_values:322`; telemetry `:369`, config `:382`, GET-producer branch `:443`, entity/catalog carve-out `:468` |
| 3 | **Correlation decision** | `correlate/decide.py` — `build_correlations:119` (gate at `:130`: `RUNTIME_GENERATED and v.consumers`), `_choose_extractor:85`, `_json_path:59` |
| 4 | **Extractor validation** | `validate/extractors.py` — `verify_extractors:255`, `_check_json:136`, `_check_regex:229` |
| 5 | **JMX substitution** | `emit/jmx.py` — `_build_sub_map:130`, `_sub_lookup:156`, `_apply:178`, `_apply_header:186`, `_sub_json:200`, `_sub_path:219`, `_sub_ok:89` |
| 6 | **Materialization audit** | `validate/materialization.py` — `audit_materialization:118` |
| 7 | **Plan validation** | `emit/validate.py` — `validate_plan:23` (surfaces `MATERIALIZATION_FAILED`) |

The architecture already implements the requested shape: *provenance → dependency → decision →
deterministic validation → JMX audit*. It is not score-driven; correlation only happens when a value is
classified runtime-generated **and** has a proven consumer **and** its extractor verifies **and** the
JMX audit confirms substitution.

---

## 2. What already works (measured, 44 real workflows)

| Property | Result |
|---|---|
| **Precision** | **1.000** |
| **False correlations** | **0** |
| **Unnecessary extractors** | **0** — 32 emitted, all 32 expected (census run for this analysis) |
| **Verified extractor rate** | **1.000** |
| **Materialization rate** | **1.000** |
| Conversion | 112 HARs, 100%, 0 crashes |
| Authentication | 4/4 correlations; 6/6 credentials parameterized; 0 false |
| Recall excl. policy + floor | 0.842 |

Shapes at full recall: JSON→header, JSON→body, path+suffix, nested JSON, arrays of objects **and of
scalars**, UUID, JWT, opaque tokens, POST producers (8/8), one-producer→multiple-consumers,
multiple-producers, encoded values, create→retrieve, create→update, CSRF, refresh chains.

Negative behaviour is already correct and proven: unused `refresh_token`, **superseded** access token,
unused auth token, passwords, OTP, browser timing telemetry, config enums — **none** correlated.

---

## 3. Where misses occur (16 of 48)

| Cause | n | Verdict |
|---|---|---|
| POLICY — entity/catalog carve-out | 8 | intentional (product decision) |
| DISCOVERY — consumer slot never matched | 5 | **SYSTEMATIC** |
| FLOOR — below short-value minimum | 2 | intentional |
| NOISE — workflow dropped entirely | 1 | **P1 defect** |

**DISCOVERY (5 apps, 4 domains)** — Crossref DOI, Hugging Face models, Hugging Face datasets
(multi-segment ids), Nominatim `osm_ids=R<id>`, OpenAlex (trailing id). Producer found, consumer slot
never matched. Multi-segment ids (`10.x/y`, `org/repo`) are a mainstream identifier style.

**NOISE (P1)** — a JSON business API is excluded as `RequestRole.STATIC` "static resource path" because
its path contains a media word. `…/v1/images/?q=cat` and `…/v1/media/search?q=cat` are dropped while
`…/v1/photos` and `…/v1/audio/` are kept; content type is ignored. Openverse's whole workflow produced
a plan with **no samplers**. Losing a correlation costs one value; losing the workload costs the script.

---

## 4. Where over-correlation occurs

**Nowhere measurable.** Census: 0 unnecessary extractors across 44 workflows; 0 false correlations.

One near-miss worth recording: on both Hugging Face workflows the engine correlated a **sibling** field
(`author`, `library_name`) whose value equals the first path segment. Both are genuine
producer→consumer dependencies and both materialized correctly, so precision is unharmed — but for
`library_name` the match is **coincidental** (it happens to equal the org name). If the multi-segment
gap is fixed, the correct id should win and this coincidence should disappear.

---

## 5. Multi-run differential — tested, and it must NOT become a trigger

Captured the same restful-booker flow three times with deliberately different user input:

| Value | Run A | Run B | Run C | Varies | Origin |
|---|---|---|---|---|---|
| `token` | 93c0bac31e6242d | ca32e8dc47f48b7 | 30522b5a3ce6b72 | yes | **server** |
| `bookingid` | 4890 | 4896 | 4903 | yes | **server** |
| `firstname` | Alice | Bob | Cara | yes | **user** |
| `checkin` | 2026-03-01 | 2026-03-01 | 2026-03-01 | no | user |
| `additionalneeds` | Breakfast | Breakfast | Breakfast | no | user |

**`firstname` varies across runs, is echoed by the server, and reappears in the downstream response.**
A rule of the form *"changes across runs ⇒ correlate"* would make it a false correlation — exactly the
trap the brief warns about. Run-to-run variation does **not** separate server-generated from
user-controlled values.

What does separate them is **provenance**, which stage 2 already computes: whether the value's earliest
occurrence is a *request* (client-originated → parameterize, even when echoed) or a *response*
(server-originated → correlation candidate). The engine already gets this case right: it correlates
`bookingid` and parameterizes `firstname`, `checkin`, `additionalneeds`, `totalprice`.

**Conclusion: multi-run differential would add confidence but no new discriminating power, while adding
a large new input contract (multiple aligned HARs) and a real false-positive risk. Recommend NOT
implementing it.** The single-HAR provenance evidence is strictly stronger and already in place.

---

## 6. Can the architecture support what is being asked?

**Yes, without redesign.**

* Provenance chain — already modelled (`ValueFlow.first_producer` / `producers` / `consumers`).
* Necessity gate — already exists as the conjunction at `decide.py:130` plus the classification carve-outs.
* Deterministic validation — already exists (stages 4, 6, 7) and is what keeps precision at 1.000.
* Evidence/confidence model — `ValueVerdict.confidence` and `reason` already carry per-decision
  evidence. An additive score is **not** needed: the deterministic conjunction is doing the job, and a
  threshold would be a way to *lose* precision.

The remaining gaps are **not architectural**. They are two narrow, locatable behaviours:
one noise rule keying on a path word, and one missing consumer-slot shape.

---

## 7. Smallest safe change

Ordered by value-to-risk. Each is measured against this corpus, and none may reduce precision or
materialization.

### Change 1 — noise: do not exclude a JSON API by path word (P1)
`classify/request_noise.py`. A request whose response is `application/json` (or any structured API
content type) and which carries a real API shape must not be classified `STATIC` purely because a path
segment reads `images`/`media`. Use the existing role+relevance evidence the module already has.
*Blast radius:* recovers whole workloads. *Risk:* low — it narrows an exclusion; it cannot create a
correlation on its own. Recovers 1 benchmark workflow and its correlation.

### Change 2 — discovery: multi-segment / slash-bearing id as a consumer slot
`lineage/graph.py::_request_slots`. Path-prefix slots already exist but only match values that begin
with `/`. Emit the same cumulative prefixes **without** the leading slash so `10.1002/9781119584414.ch4`
and `sentence-transformers/all-MiniLM-L6-v2` match, and extend `emit/jmx.py::_sub_path` symmetrically.
*Risk:* moderate — request-side slots only, so no new producers; every candidate still passes
classification, extractor verification and the JMX audit. Addresses 3 of the 5 discovery misses.

### Change 3 — (only after 1 and 2 are measured) embedded/derived consumer values
Nominatim `R<id>` and OpenAlex trailing-id. This is the substring matching that was deliberately removed
once before to kill false positives. It should be attempted **last**, narrowly, and abandoned if the
corpus shows any precision loss.

### Explicitly NOT proposed
* Multi-run differential as a correlation trigger — §5 shows it would create false correlations.
* A score-threshold decision model — would trade away the deterministic precision that is at 1.000.
* Changing the entity/catalog carve-out — it causes 8 of 16 misses, but that is a **product decision**
  for you, not a defect, and the brief says preserve it absent contrary evidence.
* Any field-name rule or keyword list.

**Invariants to hold on every step:** precision 1.000, materialization 1.000, zero false correlations,
zero unnecessary extractors, suite green.
