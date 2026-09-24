# Final Real-World Benchmark — 44 workflows

**Engine frozen throughout this phase.** `git status src/` is clean; the only code changes were RC-A and
RC-D, applied and verified *before* capture. Suite **539 passed**; 112 HARs, **100% conversion, 0 crashes**.

Data: `SHAPE_MATRIX_V3.json` · ground truth: `expected/shape_matrix_v3.py` · HARs: `normalized/`, `real/`.

---

## 1. Headline

| Metric | 13-wf | 26-wf | **44-wf (final)** |
|---|---|---|---|
| Real workflows | 13 | 26 | **44** |
| Expected correlations | 14 | 27 | **48** |
| Detected | 10 | 17 | **32** |
| Recall | 0.714 | 0.630 | **0.667** |
| Recall excl. policy + floor | 0.769 | 0.708 | **0.842** |
| **Precision** | 1.000 | 1.000 | **1.000** |
| **False correlations** | 0 | 0 | **0** |
| **Verified extractor rate** | 1.000 | 1.000 | **1.000** |
| **Materialization rate** | 1.000 | 0.941 | **1.000** |

**All four invariants held across 44 independent applications**: precision 1.000, zero false
correlations, verification 1.000, materialization 1.000. Adjusted recall rose 0.708 → **0.842**.

By producer method: **POST 8/8 (1.00)** · GET 24/39 (0.62) · PUT 0/1.

### Corpus
| Bucket | HARs | Correlations |
|---|---|---|
| REAL_CAPTURE (full browser) | 2 | 2 |
| REAL_API_JOURNEY | 42 | 30 |
| REAL_API (pre-existing probes) | 11 | 8 |
| **SYNTHETIC_MFA** (not scored) | 1 | 2 |
| SYNTHETIC (labelled) | 56 | 96 |

---

## 2. Authentication — 100%

| Metric | Result |
|---|---|
| Auth workflows | 3 |
| Expected auth correlations | 4 |
| **Detected / verified / materialized** | **4 / 4 / 4 (1.000)** |
| Credentials parameterized | **6 / 6** (`username`,`password`,`email` ×2, `username`,`password`) |
| False auth correlations | **0** |

| App | Pattern | Server value | Result |
|---|---|---|---|
| Quotes to Scrape | form-urlencoded + CSRF | `csrf_token` (HTML hidden input → body) | ✅ |
| Platzi | email+password → Bearer | `access_token` | ✅ |
| DummyJSON | refresh chain | `refreshToken` → body, `accessToken` → header | ✅ ✅ |

**True negatives all held:** Platzi's unused `refresh_token`, DummyJSON's **superseded** first
`accessToken`, restful-booker's unused auth `token`, and every `password` — none correlated.

**Authentication generalizes.** Three unrelated applications, three different patterns, no domain rules,
100% correct split between correlate and parameterize.

## 3. MFA — real BLOCKED, synthetic PASSES

Real MFA remains **BLOCKED** (no public sandbox exposes a capturable challenge/OTP; a self-hosted IdP
would require creating an account). **No real MFA result is claimed.**

`SYNTHETIC_MFA — NOT REAL-WORLD BENCHMARK` (excluded from every real figure):

| Value | Expected | Actual |
|---|---|---|
| `challengeId` | CORRELATE | ✅ correlated, verified, materialized |
| `accessToken` (post-MFA) | CORRELATE | ✅ correlated, verified, materialized |
| `otp` | PARAMETERIZE | ✅ CSV — **not** correlated |
| `username`, `password` | PARAMETERIZE | ✅ CSV |

The critical MFA trap — treating a dynamic OTP as a server-generated correlation — **did not occur**.

---

## 4. Misses, grouped by root cause

| Stage | n | Verdict |
|---|---|---|
| **POLICY** — entity-identifier carve-out | **8** | intentional |
| **DISCOVERY** — consumer slot never matched | **5** | **SYSTEMATIC** (upgraded) |
| **FLOOR** — below short-value minimum | 2 | intentional |
| **NOISE** — workflow dropped entirely | 1 | **P1 DEFECT** |

### 4.1 POLICY (8 apps) — the carve-out is now the dominant miss category
Nominatim, HAPI FHIR, Wikidata, DummyJSON products, Art Institute, TVMaze, crates.io, UK Police.
All are search→detail where the id is a discovered entity identifier, so it is parameterized rather
than correlated. **This behaves exactly as agreed** — but it now accounts for **half of all misses**,
and in each case the dependent id lands in a **single-row CSV column**, so at replay every virtual user
uses the same recorded id and the search result is discarded. Flagged for your decision in §6.

### 4.2 DISCOVERY — **RC-B/RC-C are now SYSTEMATIC, not isolated**
Five independent applications, all "producer found, consumer slot never matched":

| App | Produced value | Consumer |
|---|---|---|
| Crossref | `10.1002/9781119584414.ch4` | path spanning 2 segments |
| **Hugging Face models** | `sentence-transformers/all-MiniLM-L6-v2` | path spanning 2 segments |
| **Hugging Face datasets** | `m-a-p/FineFineWeb` | path spanning 2 segments |
| Nominatim | `311466843` | `osm_ids=R311466843` (embedded) |
| OpenAlex | `https://openalex.org/W2069091362` | trailing id reused |

**This changes my earlier recommendation.** At 26 workflows RC-C was ISOLATED (1 app) and RC-B EMERGING
(2). At 44 workflows the combined class hits **5 independent applications across 4 domains**
(publishing, AI ×2, geo, research). Multi-segment/slash-bearing ids are a mainstream identifier style
(DOIs, HF repo ids, `org/repo`, file paths).

Worth noting: on both Hugging Face workflows the engine *did* correlate a **sibling** field that equals
the first path segment (`author`, `library_name`) — a real dependency, correctly materialized, so
precision is unharmed — but the second segment stays hardcoded, so the script is only partly parameterized.

### 4.3 NOISE — **DEF-N1, P1, new and systematic in shape**
`api.openverse.org/v1/images/?q=cat` and its detail call are classified `RequestRole.STATIC`
("static resource path") and **excluded**, so the generated plan has **no samplers at all** —
`validate_plan` reports *missing constituents: HTTP Request Defaults, ResponseAssertion,
TransactionController, HTTPSamplerProxy*. Reproduced generically:

| URL (all `application/json`) | Excluded |
|---|---|
| `…/v1/images/?q=cat` | **YES** |
| `…/v1/media/search?q=cat` | **YES** |
| `…/v1/photos?q=cat` | no |
| `…/v1/audio/?q=jazz` | no |

The decision keys on a path *word* (`images`, `media`) irrespective of the JSON content type. This
affects any media/asset/DAM/CMS API and it is the **most severe finding in this benchmark**: losing a
correlation costs one value; losing the workload costs the whole script.

### 4.4 FLOOR (2) — intentional
reqres `3`, DummyJSON `78`. Both below the documented minimum. PUT scores 0/1 only because its single
case is this floor case — **not** evidence that PUT producers fail (the PUT *did* produce the id and
lineage found 3 producers / 2 consumers).

---

## 5. Parameterization & CSV

49 CSV columns across 44 workflows — **1.1 per workflow**. Spot checks: restful-booker produced
`username,password,firstname,lastname,totalprice,checkin,checkout,additionalneeds` — every column a
genuine booking input. No telemetry column appeared in any real workflow. No server-generated value was
put into CSV **except** the 8 POLICY cases, which are there by design.

---

## 6. Answers to the ten engineering questions

1. **Correlation gaps remaining?** Multi-segment / embedded consumer values (5 apps) and the short-value
   floor (2). Nothing else.
2. **Parameterization gaps?** None observed — CSV stayed minimal and telemetry-free.
3. **Does RC-B deserve implementation?** **Now yes, jointly with RC-C** — 5 apps, 4 domains. It was
   correctly deferred at 26 workflows; the evidence has since crossed the bar.
4. **Does RC-C deserve implementation?** **Yes — highest value.** 3 of the 5 are pure multi-segment ids
   (DOI, two HF ids), the most mainstream identifier style still unsupported.
5. **New systematic gaps?** **Yes — DEF-N1 noise (P1)**: JSON business APIs dropped because their path
   contains `images`/`media`.
6. **Does authentication generalize?** **Yes** — 3 unrelated apps, 3 patterns, 4/4 correlations, 6/6
   credentials, 0 false positives.
7. **Is MFA logic correct?** Correct on the synthetic fixture (challenge + post-MFA token correlated,
   OTP parameterized). **Unproven on real traffic** — real MFA is BLOCKED.
8. **Detected but not materialized?** **Zero.** Materialization 1.000 across all 32.
9. **Server values wrongly in CSV?** Only the 8 POLICY cases, by design — see §6 decision below.
10. **CSV minimal?** Yes — 1.1 columns per workflow, no telemetry.

### Recommended next work, in order
1. **DEF-N1 noise (P1)** — stop excluding a JSON API because its path contains a media word. Smallest
   change, largest blast radius: it currently destroys entire workloads.
2. **RC-C, then RC-B** — now justified by 5 independent applications.
3. **Revisit the entity-identifier carve-out** — it causes half of all misses, and each one degrades to
   a single-row CSV column that severs the dependency. *This is a product decision, not a defect.*
   A candidate narrowing: correlate when the producing response returned **one** candidate (a
   search→detail journey) and keep parameterizing when it returned **many** (a genuine catalog to
   spread load across).
4. Leave the short-value floor alone.

**Protect throughout:** precision 1.000, materialization 1.000, zero false correlations, zero hardcoded
accepted runtime dependencies, minimal CSV. Every fix above must be measured against this corpus, and
none of it is worth trading for recall.
