# HAR → JMeter Converter — Real-World Black-Box Baseline

> **STATUS — superseded in part (2026-09-24).** The correlation defects below were subsequently fixed.
> Correlation recall on this benchmark moved **0/6 → 4/6** (0.80 excluding the one value below the
> documented short-value floor), precision 1.0, **0 false correlations**, synthetic correlations
> 94 → 96 (nothing lost), suite 527 passed. See `REMEDIATION.md`. The measurements in this report are
> the untouched BASELINE and are kept as the before-picture.

**Date:** 2026-09-24 **Tool version:** committed `main` baseline, worktree `feat/param-priority-urls`
**Rule observed:** the converter was **not modified** during this baseline (Phase 9).

---

## 0. Honest scope statement (read this first)

The brief asked for ~50 **real applications**. That target was **not met, and was not faked.** What was
actually done:

| Bucket | n | What it is |
|---|---|---|
| `REAL_CAPTURE` | **2** | Full browser captures (page load + static + third-party + analytics beacons + API journey) |
| `REAL_API_JOURNEY` | **4** | Live journeys against real public APIs (no browser UI, so no static/ad noise) |
| `REAL_API` | 11 | Pre-existing hand-authored probes that hit **real** public API hosts |
| `SYNTHETIC` | 56 | Pre-existing hand-authored fixtures on `*.example.com` |
| **Total run** | **73** | 100% conversion success, 0 crashes |

**6 applications were genuinely captured by me** (OpenLibrary, Wikipedia, PokeAPI, OpenFoodFacts,
reqres.in, Nominatim/OpenStreetMap). Every byte in those HARs was observed live in the browser.

### Why not 50
1. **Login-gated domains are BLOCKED.** Banking, healthcare, insurance, CRM and ERP demos require
   authentication. I am not permitted to enter passwords — including published demo credentials — so
   those journeys cannot be captured. They remain covered only by clearly-labelled SYNTHETIC fixtures.
2. **Anti-bot protection is BLOCKED and was not bypassed.** `demo.opencart.com` returned a Cloudflare
   "security verification" interstitial; per the brief it was recorded BLOCKED, not circumvented.
3. **Fabrication was refused.** No HAR was invented and no expected-correlation was made up.

### Pre-existing corpus provenance — a material finding
Before this benchmark the repository contained **zero genuine browser captures**. All 67 HARs are
hand-authored probes: 2–11 entries, almost all single-host, creator strings like `library_openlibrary|1.0`.
A real capture is 28–51 entries across 2–6 hosts with static assets, third-party CDNs and analytics
beacons. **The converter had therefore never been evaluated against realistic browser traffic.**
The prior `stress50.py` "50-application" artefact is a **generator of synthetic HARs** (its own docstring
says so) — it is a legitimate synthetic benchmark, but it is not 50 real applications.

---

## 1. Headline results

### Conversion (Phase 3)
| Metric | Result |
|---|---|
| HARs run | 73 |
| Conversion success | **73 / 73 (100%)** |
| Crashes | **0** |
| Max conversion time | < 0.1 s |
| `validate_plan` problems | 0 |

**The converter is robust.** It never crashed, never produced invalid XML, and handled real captures
(51 entries, 6 hosts, Sentry/Matomo/EventLogging beacons, iframes, 200 KB script bundles) without error.

### Correlation on REAL applications (Phase 4C) — the critical result
| Metric | Result |
|---|---|
| Applications scored | 6 |
| Expected correlations (hand-labelled) | 6 |
| **Detected correlations** | **0** |
| **Correlation recall** | **0.00** |
| Correlation recall excluding the one below documented threshold | **0.00** (0/5) |
| False correlations | **0** |
| Dependent values **miscast as CSV parameters** | **3** |

For contrast, the same engine produces **94 correlations across 56 SYNTHETIC fixtures**.
**The engine correlates what its fixtures look like, and does not correlate what real APIs look like.**

### Parameterization / CSV (Phase 4D/4E)
| Metric | Result |
|---|---|
| Unnecessary CSV columns on real apps | **7** |
| Missed business parameters | 2 |
| Dependent server values turned into CSV columns | 3 |

---

## 2. Per-application evidence

| App | Domain | Reqs | Kept | Expected corr | Detected | CSV produced | Verdict |
|---|---|---|---|---|---|---|---|
| OpenLibrary | Library | 51 | 7 | 1 | **0** | `q`, `donation_identifier`, `action_name`, `pv_id` | **FAIL** |
| Wikipedia | Knowledge/media | 28 | 5 | 1 | **0** | `pageid`, `srsearch` | **FAIL** |
| PokeAPI | Media/gaming | 2 | 2 | 1 | **0** | — | **FAIL** |
| OpenFoodFacts | Retail/food | 2 | 2 | 1 | **0** | `code` | **FAIL** |
| reqres.in | SaaS | 2 | 2 | 1 | **0*** | — | **PARTIAL*** |
| Nominatim | Geo/logistics | 2 | 2 | 1 | **0** | `place_id`, `name` | **FAIL** |

\* reqres's dependent id is the single digit `3`, below the converter's documented minimum
correlatable length. Scored separately so the tool is judged against its stated contract.

### Worked example — Wikipedia (the clearest defect)
```
GET  api.php?action=query&list=search&srsearch=performance%20engineering
  -> {"query":{"search":[{"title":"Performance engineering","pageid":6615610,...}]}}
GET  api.php?action=query&pageids=6615610&prop=info|categories      <-- depends on pageid
GET  api.php?action=query&pageids=6615610&prop=extracts             <-- depends on pageid
```
* **Expected:** extract `pageid` → `${pageid}` → reuse in both downstream requests.
* **Actual:** 0 correlations. `pageid` became a **single-row CSV column**.
* **Replay consequence:** every virtual user sends the hardcoded id `6615610`; the search response is
  discarded. The script no longer tests the search→detail dependency and breaks when the dataset changes.

---

## 3. Noise / telemetry (Phase 4B)

On the two full browser captures the tool excluded **44/51** and **23/28** requests correctly — static
JS/CSS/images, Sentry envelopes, `athena.archive.org` pageview gifs. Two classes leaked:

| Leaked as business traffic | Why it matters |
|---|---|
| `apollo.archive.org/matomo.php?action_name=...` | Matomo analytics beacon — pure telemetry |
| `archive.org/includes/donate.php?...` | Third-party donation iframe — not the workload |
| `en.wikipedia.org/ins-502b/v2/events` | **First-party** EventLogging beacon — same host as the business API, so host-based rules cannot separate it |

These leaks **cause** the CSV pollution: `donation_identifier`, `action_name` and `pv_id` are query
parameters harvested from exactly these three requests. Fixing the noise classification removes 3 of the
7 unnecessary CSV columns for free — one root cause, two symptoms.

---

## 4. Root causes (Phase 7) — ranked

### RC-1 — `GET`-producer ⇒ parameterize (blocks 3 of 6 apps; **P1**)
`src/har2jmx/classify/value_engine.py` (~line 363):
```python
elif method == "GET" or search:
    cls = ValueClass.BUSINESS_MASTER_DATA        # "existing record selected, not created"
```
`build_correlations` (`correlate/decide.py:118`) only accepts `RUNTIME_GENERATED`, so any value whose
producer was a GET can **never** be correlated. Every real search→detail journey has a GET producer.
Confirmed verdict string on Wikipedia, OpenFoodFacts and Nominatim, where lineage **did** discover the
consumers — only this rule blocks them. It also drives the 3 miscast CSV columns.

### RC-2 — whole-slot matching misses composite paths and absolute URLs (blocks 2 of 6 apps; **P1**)
`src/har2jmx/lineage/graph.py` matches complete slots. Observed `consumers=0` despite genuine reuse:
* OpenLibrary: producer value `/works/OL1904498W`; consumer path segments are `works` + `OL1904498W.json`.
  The composite path value never equals a single segment.
* PokeAPI: producer value is the **absolute URL** `https://pokeapi.co/api/v2/pokemon/1/`, reused verbatim
  as the next request's URL. Lineage emits path *segments*, never the full URL, so it cannot match.

This is the HATEOAS / `_links` / `href` / `self` pattern — ubiquitous in real REST APIs and **absent from
every fixture in the repo**. Note RC-2 is *upstream* of RC-1: fixing RC-1 alone leaves these two failing.

### RC-3 — short-value floor (1 of 6 apps; **P3**, documented behaviour)
Values under the length floor never enter lineage (`reqres` `id=3`). This is a deliberate
ambiguity guard, not a bug, but it does cap recall on APIs with small integer ids.

### RC-4 — first-party telemetry endpoints not recognised (**P2**)
Host/third-party heuristics cannot classify `en.wikipedia.org/ins-502b/v2/events` or
`apollo.archive.org/matomo.php`, because they are same-host or CDN-shaped. Causes both noise
false-negatives and downstream CSV pollution.

---

## 5. Phase-8 questions, answered from measurement

1. **Usable script from an unmodified real HAR?** It always *produces* a script (6/6), but on 0/6 real
   apps is it replay-correct — every one has an unresolved server-issued dependency.
2. **Crash rate?** 0 / 73.
3. **Valid correlations detected?** 0 of 6 on real apps; 94 on synthetic fixtures.
4. **Valid correlations missed?** 6 of 6 (5 of 5 excluding the documented threshold case).
5. **What does it consistently miss?** Values produced by a **GET/search** response and consumed
   downstream — i.e. the standard search→detail journey — plus composite-path and absolute-URL reuse.
6. **Different producer/consumer field names?** Yes, it handles this well **when the producer is a POST**
   (proven by targeted tests); the failure is the producer *method*, not the field name.
7. **Opaque/JWT/Base64/UUID values?** Yes, when server-*created*. Not when GET-returned.
8. **Business inputs across domains?** Partially — it found `q`, `srsearch`, `categories_tags_en`, but
   missed 2 and added 7 unnecessary columns.
9. **Is CSV minimal?** No. 7 of 13 real-app CSV columns are unnecessary (54%).
10. **Does it parameterize browser telemetry?** **Yes** — `action_name`, `pv_id`, `donation_identifier`.
11. **Third-party noise remaining?** 3 leaked requests across 2 captures (~4% of noise).
12. **PE workload or browser replay?** Closer to a PE workload: it strips ~86% of a real page's requests.
13. **Executable without manual repair?** **No** for all 6 real apps — each needs correlation added by hand.
14. **Isolated edge cases?** RC-3 only.
15. **Architectural weaknesses?** RC-1 and RC-2 — both are single-point rules whose assumptions do not
    hold for real REST APIs.

---

## 6. Recommended next engineering priorities (Phase 10) — smallest change, largest gain

**Do not rewrite the correlation engine.** It is precise (0 false correlations) and robust (0 crashes);
it is *under-recalled* on one specific, very common shape.

1. **RC-2 first** (enables RC-1's benefit): teach lineage to match a produced value that is reused as a
   **URL path prefix/segment** or as an **absolute request URL**. This is discovery, not policy, and it
   cannot create false correlations on its own.
2. **RC-1 second, narrowly:** when a GET-produced value has a **proven downstream consumer inside the same
   journey**, prefer CORRELATE over PARAMETERIZE — or at minimum stop emitting it as a single-row CSV
   column. *This touches the frozen correlate-vs-parameterize policy, so it needs an explicit decision
   from you rather than a unilateral change.*
3. **RC-4:** recognise beacon/telemetry **endpoints** structurally (tiny/opaque response, no downstream
   dependency, fire-and-forget) rather than by host. Removes 3 leaked requests and 3 CSV columns.
4. Leave RC-3 alone unless small-integer ids matter to you.

**Protect what works:** conversion robustness, XML validity, assertion placement, think-time scoping,
noise removal of classic static/analytics, and correlation precision — all measured clean.

---

## 7. Reproducing this
```bash
python benchmark/capture/app01_openlibrary.py
python benchmark/capture/app02_wikipedia.py
python benchmark/capture/apps03_06_api_journeys.py
python benchmark/run_baseline.py                      # -> APPLICATION_SCORECARD.csv, RAW_RESULTS/
PYTHONPATH=src python benchmark/expected/ground_truth.py   # -> CORRELATION_SCORE.json
```
The corpus is reusable as a regression suite: `benchmark/raw/` holds the untouched captures,
`benchmark/normalized/` the evaluation HARs, `benchmark/expected/ground_truth.py` the labels.
