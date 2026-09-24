# Correlation Remediation — before / after against the real benchmark

Scope: correlation **discovery**, **classification** and **validation** only. Parameterization logic,
noise classification, transaction grouping and unrelated JMX behaviour were not touched.

## 1. Results

| Metric (6 real captured applications) | Before | After |
|---|---|---|
| Expected correlations (hand-labelled) | 6 | 6 |
| **Detected** | **0** | **4** |
| **Recall** | **0.00** | **0.667** |
| Recall excluding the below-threshold case | 0.00 | **0.800** |
| **False correlations** | 0 | **0** |
| Precision | n/a | **1.00** |
| Dependent values miscast as CSV parameters | 3 | **1** |
| Unnecessary CSV columns | 7 | 5 |

| Corpus-wide (73 HARs) | Before | After |
|---|---|---|
| Conversion success | 73/73 | 73/73 |
| Crashes | 0 | 0 |
| REAL_CAPTURE correlations | 0 | **2** |
| REAL_API_JOURNEY correlations | 0 | **2** |
| REAL_API correlations | 5 | **6** |
| **SYNTHETIC correlations** | 94 | **96** (nothing lost) |
| Test suite | 520 | **527 passed** |

Synthetic correlations went **up**, not down — the change adds recall without regressing the shapes the
engine already handled.

## 2. What changed

### 2.1 Discovery — `src/har2jmx/lineage/graph.py`
Two reuse shapes were invisible to whole-slot matching, so the dependency was never discovered at all
(`consumers=0`):
* **Composite resource paths.** A response returning `/works/OL1904498W` reused as
  `/works/OL1904498W.json` or `/works/OL1904498W/editions.json`. Cumulative path prefixes (plus the
  extension-stripped final form) are now consumer slots.
* **Absolute URLs.** A response returning the next request's full URL (HATEOAS `_links`/`self`/`href`).
  The request URL is now a consumer slot — *except* for redirect targets, whose `Location` already has
  dedicated producer handling and redirect following; matching those would mint a redundant extractor
  with no consumer.

Both are **request-side** slots: they can add consumers, never invent a producer.

### 2.2 Classification — `src/har2jmx/classify/value_engine.py`
A value produced by a **GET/search** and consumed downstream is now `RUNTIME_GENERATED` (correlate)
instead of `BUSINESS_MASTER_DATA` (parameterize). The decisive evidence is the proven downstream
dependency, not the producer's HTTP method.

Two structural carve-outs keep catalog/master data as CSV parameters so load still spreads across a
catalog (both discovered from structure, never from field names):
1. the value is the **identifier of a discovered multi-instance entity** (`PAT-9001`, customer `1001`);
2. the value is a **structured `PREFIX-CODE` id** (`PROD-4400`, `MBR-88213`, `POL-2025-77`) — the same
   discriminator `_is_opaque_handle` already documents.

A returned value that nothing consumes also stays master data.

### 2.3 Validation — `src/har2jmx/validate/extractors.py`
A value inside a per-run list was always rejected ("match #1 would grab the wrong element"). That is
correct for a **created** id, but wrong for list/search → detail, where following whatever the search
returns this run is the entire point of correlating. Now accepted when the recorded value is match #1
**and the producer is a READ (GET)**. A POST-created id in a list, or a value at a non-first index,
still stays `UNRESOLVED` and ships as a literal for review.

### 2.4 Substitution — `src/har2jmx/emit/jmx.py`
Substitution can now express the new shapes: a correlated resource path is replaced as the **longest
prefix** of the consumer path when only a static tail follows (`.json`, `/editions.json`), and a
correlated absolute URL replaces the sampler path outright (JMeter accepts a full URL in
`HTTPSampler.path`).

## 3. Per-application, verified end to end

Each correlation was checked against the emitted JMX, not just the decision: extractor present and
**verified**, `${var}` consumed downstream, original literal removed, `validate_plan` clean.

| App | Shape | Result |
|---|---|---|
| OpenLibrary | composite path `/works/OL1904498W` → `…​.json`, `…/editions.json` | **CORRELATED** (`docKey`, 2 consumers) |
| Wikipedia | numeric id → query param `pageids=` | **CORRELATED** (`pageid`) |
| PokeAPI | absolute URL returned → requested verbatim | **CORRELATED** (`url`) |
| OpenFoodFacts | string id → path segment | **CORRELATED** (`productCode`) |
| Nominatim | `place_id` — entity identifier of a places collection | parameterized by the carve-out (by design) |
| reqres.in | id `3` | below the documented short-value floor (unchanged) |

## 4. Known remaining limitations (deliberate)

* **Short values.** `reqres`'s dependent id is the single digit `3`. Admitting 1-character values into
  lineage would merge every unrelated `3` in the capture into one flow (a `count:3` producer matching a
  `page=3` consumer), and the emit layer substitutes by **literal value**, so a 1-character variable
  would corrupt unrelated requests. Correlating it safely needs positional substitution, which is a
  redesign and was explicitly out of scope. Left unchanged.
* **Nominatim `place_id`** is parameterized rather than correlated because the engine structurally
  identifies it as an entity identifier — the catalog carve-out. This is the chosen policy, not a defect.
* Noise classification (`matomo.php`, first-party `/events` beacons) was **not** touched in this change,
  so 3 of the 5 remaining unnecessary CSV columns persist. That is `DEFECT-004/005` in the register and
  is the next highest-value fix.

## 5. Regression protection
`tests/test_correlation_read_producer.py` — the four newly-supported shapes, plus the guards:
a structured catalog code stays a parameter, a POST-created id inside a list is not resolved by match #1,
and a returned-but-unconsumed value stays master data.
