# Defect Register — Real-World Baseline (2026-09-24)

Severity: **P0** crash/no output · **P1** script logically incorrect · **P2** significant PE quality
issue · **P3** minor/enhancement. No code was changed while producing this register.

---

## DEF-001 — Value produced by a GET/search response is never correlated
| | |
|---|---|
| **Severity** | **P1** — generated script is logically incorrect |
| **Category** | CORRELATION |
| **Applications** | Wikipedia, OpenFoodFacts, Nominatim (directly); OpenLibrary, PokeAPI (also blocked by DEF-002) |
| **Frequency** | 5 of 6 real applications; 0 of 56 synthetic fixtures |

**Exact request/response (Wikipedia)**
```
GET /w/api.php?action=query&list=search&srsearch=performance%20engineering&srlimit=2&format=json
200 {"query":{"search":[{"title":"Performance engineering","pageid":6615610,...}]}}

GET /w/api.php?action=query&pageids=6615610&prop=info|categories&format=json
GET /w/api.php?action=query&pageids=6615610&prop=extracts&format=json
```

**Observed** `res.correlations == []`. Verdict for `6615610`:
`BUSINESS_MASTER_DATA :: "returned by a read (GET) and reused — existing record selected, not created"`.
Lineage **did** find the dependency (`producers=3, consumers=2`).

**Expected** Extract `pageid` from the search response into `${pageid}` and substitute it into both
downstream requests.

**Root cause** `src/har2jmx/classify/value_engine.py` (~363):
```python
elif method == "GET" or search:
    cls, life, conf = ValueClass.BUSINESS_MASTER_DATA, Lifecycle.EXISTING_BEFORE_RUN, "High"
```
`src/har2jmx/correlate/decide.py:118` only accepts `ValueClass.RUNTIME_GENERATED`, so a GET-produced
value is structurally unable to become a correlation regardless of proven downstream consumption.

**Why it matters to PE** The search→detail journey is the single most common real business flow. With
the id hardcoded (or pinned to one CSV row), the script stops exercising the dependency, every virtual
user hits the same record, and the script breaks when the backing data changes.

**Reproduction**
```bash
PYTHONPATH=src python -c "
from pathlib import Path; from har2jmx.engine import analyze
r=analyze(Path('benchmark/normalized/app02_wikipedia_search_to_article.har').read_bytes())
print(r.correlations, [c.name for d in r.parameterization.datasets for c in d.columns])"
```

**Possible fix** Where a GET-produced value has a proven consumer **within the same journey**, prefer
CORRELATE. ⚠ This modifies the *frozen* correlate-vs-parameterize policy and must be an explicit
product decision, not a unilateral change.

**Regression test needed** Yes — search→detail journey per shape (path segment, query param).

---

## DEF-002 — Dependency invisible when the value is reused as a URL path or an absolute URL
| | |
|---|---|
| **Severity** | **P1** |
| **Category** | CORRELATION (discovery) |
| **Applications** | OpenLibrary, PokeAPI |
| **Frequency** | 2 of 6 real applications |

**Exact case A — OpenLibrary**
```
GET /search.json?q=...   200 {"docs":[{"key":"/works/OL1904498W",...}]}
GET /works/OL1904498W.json
GET /works/OL1904498W/editions.json?limit=2
```
`build_lineage` reports `producers=4, consumers=0`. The produced value is the composite path
`/works/OL1904498W`; the consumer's path *segments* are `works` and `OL1904498W.json`. Whole-slot
equality never holds.

**Exact case B — PokeAPI**
```
GET /api/v2/pokemon?limit=2  200 {"results":[{"url":"https://pokeapi.co/api/v2/pokemon/1/"}]}
GET https://pokeapi.co/api/v2/pokemon/1/
```
`producers=1, consumers=0`. The produced value is an **absolute URL** reused verbatim as the next
request's URL; lineage emits path segments, never the whole URL, so no slot can match it.

**Root cause** `src/har2jmx/lineage/graph.py` — `_request_slots()` emits each path segment separately
and never the full URL or a multi-segment path prefix; matching is whole-slot by design (deliberately,
to avoid the old substring-matching false positives).

**Why it matters to PE** This is the HATEOAS / `_links` / `self` / `href` pattern used by most modern
REST APIs. It is **absent from every fixture in the repo**, which is why it was never caught.

**Possible fix** Additionally index (a) the request's full absolute URL and (b) multi-segment path
prefixes, as candidate consumer slots. Discovery-only; cannot by itself create a false correlation
because emission remains gated by extractor verification.

**Regression test needed** Yes — absolute-URL reuse, and `/collection/{id}` reused as `/collection/{id}.json`.

---

## DEF-003 — Server-issued dependent value emitted as a single-row CSV parameter
| | |
|---|---|
| **Severity** | **P1** |
| **Category** | PARAMETERIZATION |
| **Applications** | Wikipedia (`pageid`), OpenFoodFacts (`code`), Nominatim (`place_id`) |
| **Frequency** | 3 of 6 real applications |

**Observed** The dependent id appears as a CSV column with a single captured row.
**Expected** Correlate it; or, if parameterising is genuinely intended, back it with a multi-row dataset
and still honour the in-journey dependency.

**Why it matters** This is worse than leaving the value hardcoded, because the plan *looks* parameterised
and passes validation while silently severing the real dependency. Downstream this is a false green.

**Root cause** Consequence of DEF-001 (the value is classified `BUSINESS_MASTER_DATA`, which feeds
`parameterize/decide.py`).

**Regression test needed** Yes — assert a proven in-journey dependent value never becomes a CSV column.

---

## DEF-004 — Analytics/telemetry endpoints retained as business traffic
| | |
|---|---|
| **Severity** | **P2** |
| **Category** | NOISE_CLASSIFICATION |
| **Applications** | OpenLibrary, Wikipedia |
| **Frequency** | 3 leaked requests across the 2 full browser captures |

**Exact requests retained**
```
GET https://apollo.archive.org/matomo.php?action_name=search%20%7C%20Open%20Library&idsite=6&rec=1&pv_id=x2WytV...
GET https://archive.org/includes/donate.php?as_page=1&donation-identifier=MC44MDg0NjEz...
GET https://en.wikipedia.org/ins-502b/v2/events?hasty=true
```

**Observed** Classified as business requests and emitted as samplers.
**Expected** Excluded as telemetry/third-party.

**Root cause** Beacon recognition keys on known host families and path shapes. `matomo.php` and
`/ins-502b/v2/events` are not covered, and the Wikipedia beacon is **first-party** (same host as the
business API), so host-based separation is impossible in principle.

**Why it matters** Injects non-workload requests into the load profile **and** is the direct source of
DEF-005's junk CSV columns.

**Possible fix** Structural beacon signals rather than host lists: fire-and-forget request, tiny/empty
or non-JSON response, no downstream dependency on anything it returns, `navigator.sendBeacon`-style
`initiatorType`.

**Regression test needed** Yes — Matomo-shaped and first-party `/events` beacons excluded.

---

## DEF-005 — Telemetry query parameters become CSV columns
| | |
|---|---|
| **Severity** | **P2** |
| **Category** | PARAMETERIZATION |
| **Applications** | OpenLibrary |
| **Frequency** | 3 of 4 CSV columns on that app |

**Observed CSV** `q, donation_identifier, action_name, pv_id` — only `q` is a real business input.
`action_name` and `pv_id` are Matomo fields; `donation_identifier` comes from the donate iframe.

**Root cause** Downstream of DEF-004: once a beacon is treated as business traffic, its query parameters
are legitimate parameterization candidates. **Fixing DEF-004 removes this defect for free.**

**Note** This is *not* the W3C Navigation-Timing telemetry class (`fetchStart`, `domComplete`, …), which
a prior change already excludes; these are vendor analytics parameters arriving via retained requests.

**Regression test needed** Covered by the DEF-004 test.

---

## DEF-006 — Small-integer ids never enter lineage
| | |
|---|---|
| **Severity** | **P3** (documented, deliberate) |
| **Category** | CORRELATION |
| **Applications** | reqres.in (`id: 3`) |

**Observed** `lineage.by_value("3")` → not found; no verdict produced.
**Root cause** Minimum-length guards in `lineage/graph.py::_emit` (`len < 2`) and
`value_engine.classify_values` (`len < 3`), which exist to stop short values colliding across unrelated
fields (a page number vs a stock count).
**Assessment** Correct trade-off as stated; recorded so recall figures are interpreted against the
tool's real contract. Recommend **no change** unless small-integer ids matter to you.

---

## Non-defects confirmed (protect these)
| Area | Evidence |
|---|---|
| Crash resistance | 73/73 HARs converted, 0 exceptions |
| XML / JMeter validity | `validate_plan` returned 0 problems on every HAR |
| Correlation **precision** | 0 false correlations across all 6 real apps |
| Bulk noise removal | 44/51 and 23/28 requests correctly excluded on real captures |
| Assertion placement | one per transaction, nested under the anchor sampler (locked by tests) |
| Conversion speed | < 0.1 s for a 51-entry, 6-host capture |

---

## Ranking by systemic impact
| Rank | Root cause | Apps affected | Severity | Fixes on resolution |
|---|---|---|---|---|
| 1 | DEF-002 lineage cannot see path/absolute-URL reuse | 2 | P1 | unblocks correlation discovery for HATEOAS APIs |
| 2 | DEF-001 GET-producer ⇒ parameterize | 5 | P1 | DEF-001 + DEF-003 (3 miscast columns) |
| 3 | DEF-004 telemetry endpoints retained | 2 | P2 | DEF-004 + DEF-005 (3 junk columns) |
| 4 | DEF-006 short-value floor | 1 | P3 | none — accepted behaviour |

DEF-002 is ranked first because it sits **upstream** of DEF-001: on OpenLibrary and PokeAPI the
dependency is never discovered at all, so changing the classification policy alone would not fix them.
