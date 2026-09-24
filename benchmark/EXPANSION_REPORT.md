# Correlation Generalization — Expansion Benchmark (26 real workflows)

**Converter NOT modified during this pass.** `src/` is unchanged; suite 527 passed.
Data: `SHAPE_MATRIX_V2.json` · ground truth: `expected/shape_matrix_v2.py` · HARs: `normalized/`, `real/`.

---

## 1. Headline, and comparison with the 13-workflow benchmark

| Metric | 13-workflow pass | **26-workflow pass** |
|---|---|---|
| Real workflows | 13 | **26** |
| Expected correlations | 14 | **27** |
| Detected | 10 | **17** |
| Recall (raw) | 0.714 | **0.630** |
| Recall excl. policy + threshold exclusions | 0.769 | **0.708** |
| **Precision** | **1.000** | **1.000** |
| **False correlations** | **0** | **0** |
| Verified extractor rate | 1.000 | **1.000** |
| Materialization rate | 1.000 | **0.941** |

Recall fell because the expansion **deliberately targeted unfamiliar shapes**, not because anything
regressed — the 13 original workflows score identically. The important result is that **precision held at
1.000 across 26 independent applications**: the engine still never invents a correlation.

The **GET/POST asymmetry is now firmly evidenced**: **POST producers 4/4 (1.00)** vs
**GET producers 13/23 (0.565)** over 26 workflows.

---

## 2. Corpus — 13 new workflows, all new domains

| App | Domain | Dependency | Detected |
|---|---|---|---|
| Hacker News | Social/news | `[49823582,…]` (root array of numbers) → path | ❌ |
| OpenAlex | Education/research | `referenced_works[]` (array of strings) → derived id in path | ❌ |
| postcodes.io | Logistics/geo | `"S13 7JT"` → **URL-encoded** path | ⚠ detected, **not materialized** |
| Open Brewery DB | Retail/hospitality | UUID → path | ✅ |
| **HAPI FHIR** | **Healthcare** | `entry[].resource.id` → path | ❌ *(policy)* |
| **ClinicalTrials.gov** | **Government/clinical** | deeply nested `nctId` → path | ✅ |
| GBIF | Government/science | `results[].key` → path (also duplicated as `speciesKey`) | ✅ |
| npm registry | Developer platform | `objects[].package.name` → path | ❌ |
| Crossref | Education/publishing | DOI containing a **slash** → path across 2 segments | ❌ |
| Platzi Fake Store | E-commerce | POST-created id → path | ✅ |
| Deck of Cards | Gaming | opaque `deck_id` → **two** consumers | ✅ |
| SWAPI | Media/entertainment | `characters[]` (array of strings) → absolute URL | ❌ |
| Open Trivia DB | Gaming/media | opaque 64-char token → query | ✅ |

**Dropped, with reason** (so the corpus is not cherry-picked): iTunes Search, TheSportsDB, TheMealDB —
harness truncated their *producer* body, which would have scored a false miss. CKAN/data.gov — CORS
blocked. Platzi PUT (create→update) — the API returned HTTP 500 on PUT.

**Shapes still untested** (no legitimate public source found this pass): JSON→JSON body (3),
JSON→cookie (5), Base64/Base64URL (17), PUT/PATCH producer (23), create→update (29).
**Domains still untested:** insurance, CRM, ERP, telecom, banking, manufacturing, real estate,
events/ticketing — all require authenticated self-hosted stacks not stood up this pass.

---

## 3. Recall by shape (gaps only)

| Shape | Recall |
|---|---|
| **10 array of scalar STRINGS** | **0/3 — 0.00** |
| **11 array of scalar NUMBERS** | **0/1 — 0.00** |
| **19 embedded in consumer string** | **0/2 — 0.00** |
| **14 very short id** | 0/1 — 0.00 *(by design)* |
| 6 JSON → full URL | 1/3 — 0.33 |
| 12 array → HATEOAS link | 1/3 — 0.33 |
| 13 numeric id | 5/10 — 0.50 |
| 27 resource id → detail | 6/11 — 0.55 |
| 21 GET producer | 13/23 — 0.57 |
| 28 search result → selected entity | 4/7 — 0.57 |
| 1 JSON → URL path | 10/16 — 0.63 |
| 9 array of objects | 9/14 — 0.64 |

At **1.00**: JSON→header, JSON→path+suffix, UUID, JWT, opaque random string, POST producer,
multiple consumers, multiple producers, reused-after-encoding *(matching only)*, create→retrieve,
one-response→multiple-values.

By consumer location: header 1/1 · path-encoded 1/1 · query 5/6 · path 9/13 · **url 1/3** ·
**path-derived 0/1** · **path-multisegment 0/1** · **query-embedded 0/1**.

---

## 4. Missed-correlation register, grouped by ROOT CAUSE

### RC-A — Arrays of scalar values are invisible to lineage · **SYSTEMATIC**
**4 independent applications:** Rick & Morty (strings), SWAPI (strings), OpenAlex (strings),
Hacker News (numbers). Shapes 10 and 11 are **0/4 combined**.

`_walk_json` recurses into list elements but only handles `dict`/`list`, so a list of scalars emits **no
occurrences at all**. The value never enters the graph, so no later stage can recover it. This is also
why "JSON → full URL" scores 0.33 rather than 1.00: an URL inside an array of **objects** works
(PokeAPI ✅) while the identical URL inside an array of **strings** fails (Rick & Morty ❌, SWAPI ❌).

**Verdict: confirmed SYSTEMATIC.** Highest-value fix, and it is discovery-only.

### RC-B — Produced value is derived from / embedded in the consumer slot · **EMERGING (2 apps)**
Nominatim (`osm_ids=R311466843`) and OpenAlex (produced `https://openalex.org/W2069091362`, consumer uses
only the trailing `W2069091362`). Shape 19 is **0/2**. Whole-slot matching cannot see a value that is a
substring of — or a superstring of — the consumer's slot.

**Verdict: EMERGING, not yet proven systematic.** Two independent apps, but both geo/research; and this
is precisely the substring matching that was deliberately removed once to kill false positives. Needs
the strictest guards.

### RC-C — Multi-segment value not anchored at the path root · **ISOLATED (1 app)**
Crossref DOI `10.1002/9781119584414.ch4` spans two path segments. The existing path-prefix slots only
match values that begin with `/`, so a slash-bearing id that is not a rooted path is missed.
**Verdict: ISOLATED** — a near-miss of the existing path-prefix fix.

### RC-D — Catalog-code carve-out over-matches hyphenated names · **ISOLATED observation, BROAD mechanism**
npm's `performance-results-parser` is classified `BUSINESS_MASTER_DATA` because `_CODED_ID_RE`
(`^[A-Za-z]{2,}[-_]…`) treats **any** hyphenated identifier as a `PREFIX-CODE` catalog id like `PROD-4400`.
Observed once, but the mechanism will match **every kebab-case slug, package name and hyphenated id**,
which are ubiquitous.
**Verdict: 1 observation, but structurally broad — and it is a side-effect of our own carve-out.**

### RC-E — Asymmetric normalization between matching and substitution · **ISOLATED (1 app)**
postcodes.io: `"S13 7JT"` is correctly discovered, classified, **and verified** — then the consumer path
`/postcodes/S13%207JT` is left hardcoded, because lineage normalizes (`unquote`) for *matching* while
`_build_sub_map` substitutes by *raw literal*. The correlation is **reported but never materialized**.
**Verdict: ISOLATED, but it is a reporting-integrity issue** — the only reason materialization fell from
1.000 to 0.941, and it means a "correlated" count can overstate what the script actually does.

### Not defects — excluded by agreed policy (2 apps)
HAPI FHIR `Patient/4202` and Nominatim `place_id` are real dependencies deliberately parameterized by the
entity-identifier carve-out you chose. Reported separately and excluded from the adjusted recall.

### Not a defect — documented threshold (1 app)
reqres `id=3` remains below the short-value floor.

### True negative worth noting
restful-booker's opaque auth token is server-generated but nothing consumes it downstream, and the engine
correctly did **not** correlate it — across 26 workflows there were **zero** false correlations.

---

## 5. Which fixes the evidence actually justifies

| Fix | Evidence | Recommendation |
|---|---|---|
| **RC-A arrays of scalars** | **4 independent apps**, 2 shapes at 0.00 | **JUSTIFIED — do first.** Discovery-only, purely additive, emission still gated by extractor verification. Would address 4 of the 7 engine-gap misses. |
| **RC-D carve-out regex too loose** | 1 app, but the mechanism hits all kebab-case ids | **JUSTIFIED — small and low-risk.** Tighten `_CODED_ID_RE` to require a code-like tail (digits / uppercase), so `PROD-4400` still matches but `performance-results-parser` does not. |
| **RC-E normalization symmetry** | 1 app | **JUSTIFIED — correctness of reporting.** Either substitute the encoded form too, or stop counting a correlation that cannot be substituted. |
| **RC-C multi-segment id** | 1 app | **DEFER** — genuinely isolated; revisit if a second application shows it. |
| **RC-B embedded/derived values** | 2 apps | **DEFER pending more evidence** — highest false-positive risk of the set, and substring matching was removed once before for exactly that reason. |

Expected effect of RC-A + RC-D alone: **5 of the 7 engine-gap misses** addressed, taking adjusted recall
from 0.708 towards ~0.92, with precision expected to stay at 1.000 — to be **measured, not assumed**.

## 6. Reproducing
```bash
python benchmark/capture/apps14_26_expansion.py
PYTHONPATH=src python benchmark/expected/shape_matrix_v2.py   # -> SHAPE_MATRIX_V2.json
```
Hold-or-improve signal: **recall 0.630 / adjusted 0.708, precision 1.000, verified 1.000,
materialization 0.941, false correlations 0.**
