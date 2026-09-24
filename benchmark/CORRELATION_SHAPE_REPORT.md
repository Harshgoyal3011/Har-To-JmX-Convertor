# Correlation Generalization — Shape Coverage Report

**Converter not modified during this pass** (evidence collection only, per the brief).
13 real workflows, 14 hand-validated expected correlations. Raw data: `SHAPE_MATRIX.json`,
ground truth: `expected/shape_matrix.py`, HARs: `normalized/`, captures: `raw/`.

## 1. Headline

| Metric | Value |
|---|---|
| Real workflows tested | **13** |
| Expected correlations (hand-validated) | 14 |
| Detected | **10** |
| **Recall** | **0.714** (0.769 excluding the one below the documented short-value floor) |
| **False correlations** | **0** |
| **Precision** | **1.000** |
| **Verified extractor rate** | **1.000** |
| **Materialization rate** | **1.000** |
| Hardcoded dynamic values remaining | 4 (the four misses below) |

Every correlation the engine emits is real, verifies against the producer response, and actually
reaches the JMX as `${var}` with the literal removed. **The engine's problem is exclusively recall.**

## 2. Where the corpus came from

| Source | Apps |
|---|---|
| Public apps captured in-browser (with real static/analytics noise) | OpenLibrary, Wikipedia |
| Public APIs with real producer→consumer workflows | PokeAPI, OpenFoodFacts, reqres, Nominatim (×2), JSONPlaceholder, Rick&Morty, httpbin, Open-Meteo |
| Public **test sandboxes** using their own documented credentials | DummyJSON, restful-booker |

**Disclosure.** DummyJSON and restful-booker publish their test credentials in their documentation as
the intended public entry point; the login calls use exactly those. No real account was used, no access
control was bypassed, no account was created. This was the only way to cover the JWT/token shapes.
**Not captured:** self-hosted healthcare/insurance/CRM/ERP stacks — standing up Docker apps and creating
local users was out of reach this pass, so those domains remain represented only by labelled synthetic
fixtures. **Dropped:** TheMealDB — the harness truncated its *producer* body, which would have scored a
false "missed correlation".

## 3. Recall by correlation shape

| # | Shape | Recall |
|---|---|---|
| 4 | response JSON → request header | **1/1** |
| 7 | path → path segment + suffix | **1/1** |
| 8 | producer/consumer field names differ | **4/4** |
| 9 | nested JSON → downstream | **2/2** |
| 13 | UUID | **1/1** |
| 14 | JWT-like token | **1/1** |
| 18 | POST/create producer | **3/3** |
| 20 | one producer → multiple consumers | **4/4** |
| 25 | generated id → detail request | **3/3** |
| 27 | generated business entity id → later operation | **1/1** |
| 1 | response JSON → URL path | 4/5 (0.80) |
| 11 | numeric generated id | 3/4 (0.75) |
| 2 | response JSON → query param | 4/6 (0.67) |
| 10 | array element → downstream | 4/6 (0.67) |
| 17 | GET/search producer | 4/6 (0.67) |
| 24 | HATEOAS hyperlink → request | 2/3 (0.67) |
| 6 | response JSON → complete downstream URL | 1/2 (0.50) |
| **12** | **short generated id** | **0/1 — GAP** |
| **23** | **value embedded in larger string** | **0/1 — GAP** |

By producer method: **POST 3/3 (1.00)** vs **GET 7/11 (0.64)**.
By consumer location: header 1/1, path 4/5, query 4/5, **url 1/2**, **query-embedded 0/1**.
By value type: jwt/uuid/string-id/path-string all 1.00; numeric 5/7; **absolute-url 1/2**; **short-numeric 0/1**.

## 4. The four misses, by failure stage

| App | Value | Stage | Cause |
|---|---|---|---|
| Rick & Morty | `https://…/api/character/1` | **DISCOVERY** — never emitted as a producer | **`_walk_json` drops scalar list items.** It recurses into list elements but only handles dicts/lists, so `"characters": ["url1","url2"]` — an **array of scalars** — yields *no* occurrences at all. |
| Nominatim (embed) | `311466843` | **DISCOVERY** — producer found, consumer never matched | Consumer sends `osm_ids=R311466843`. The value is a **substring** of the slot. Whole-slot matching cannot see it; `_augment_embedded` only covers a value embedded in a *producer response*, not in a *consumer request*. |
| reqres | `3` | **DISCOVERY** — below length floor | Documented short-value guard. Unchanged by design. |
| Nominatim (detail) | `275905280` | **CLASSIFICATION** | The entity-identifier carve-out: structurally an identifier of a places collection → catalog master data → parameterized. This is the agreed policy, not a defect. |

**False correlations: 0.** Notably, restful-booker's opaque auth token `817d15644a2398c` is
server-generated but **nothing downstream consumes it in that capture** — and the engine correctly did
**not** correlate it. That is the right call and is recorded as a true negative in the ground truth.

## 5. Systematic gaps vs isolated edge cases

**Systematic (worth fixing):**
1. **Arrays of scalar values are invisible to lineage.** `"ids": [...]`, `"characters": [urls]`,
   `"tags": [...]` are everywhere in real APIs. One missed dependency here per journey, and the value
   cannot be discovered at *any* later stage because it never enters the graph. This also explains why
   shape 6/24 (HATEOAS) scores 0.5 rather than 1.0 — PokeAPI's URL sits in an array **of objects**
   (works), Rick & Morty's in an array **of strings** (fails).
2. **Value embedded in a consumer slot** (`R<id>`, `Bearer <t>`-style prefixes, `id:<v>` composites).
   Currently only the producer side has embedded handling.

**Isolated / by design:**
3. Short-value floor (shape 12) — deliberate collision guard; needs positional substitution to fix safely.
4. Nominatim entity-identifier classification — the agreed catalog carve-out.

**False-positive risk assessment.** Precision is currently 1.000 and every guard is holding:
a returned-but-unconsumed token was not correlated, catalog codes stayed parameters, and a POST-created
id inside a list was not resolved by match #1. Any fix must preserve that.

## 6. Recommended next improvements (highest value first)

1. **Emit scalar list items in `_walk_json`** (`lineage/graph.py`). Small, contained, and purely
   additive to *producer* discovery. Risk: more flows, so it must be measured for false correlations —
   but emission is still gated by extractor verification, and a JSON extractor for an array element
   needs match-number handling, which the read-producer path already supports.
2. **Consumer-side embedded matching**, narrowly: only when a produced value ≥ 6 chars appears in a
   consumer slot bounded by a short static affix, and only when the affix is stable. Higher risk —
   substring matching was deliberately removed once before to kill false positives, so it needs the
   strictest guards and a corpus-wide false-correlation check.
3. Leave the short-value floor and the entity carve-out alone unless you want to revisit them explicitly.

## 7. Regression corpus

Every HAR, capture record and label is preserved and re-runnable:

```bash
python benchmark/capture/apps03_06_api_journeys.py
python benchmark/capture/apps07_13_shapes.py
PYTHONPATH=src python benchmark/expected/shape_matrix.py    # -> SHAPE_MATRIX.json
```
Current signal to hold or improve: **recall 0.714, precision 1.000, materialization 1.000, false 0.**
