# Correlation Analysis — Real Applications vs Synthetic Fixtures

Ground truth: `benchmark/expected/ground_truth.py` (hand-labelled from the captured HAR bodies, never
from the converter's output). Scores: `benchmark/CORRELATION_SCORE.json`.

## 1. Scores

| Bucket | HARs | Expected corr. | Detected | Recall | False corr. | Precision |
|---|---|---|---|---|---|---|
| REAL (captured by this benchmark) | 6 | 6 | **0** | **0.00** | 0 | n/a (no detections) |
| REAL, excluding documented threshold case | 5 | 5 | **0** | **0.00** | 0 | n/a |
| SYNTHETIC fixtures (not ground-truth labelled) | 56 | — | 94 emitted | — | — | — |

**Precision is not the problem — recall is.** The engine emitted **zero false correlations** on real
applications. It is conservative and correct when it fires; it simply does not fire.

## 2. The correlation shapes that fail

Each real app was chosen to probe a *different* reuse shape. All six failed, for two different reasons.

| # | App | Producer → consumer shape | Lineage found consumers? | Blocked by |
|---|---|---|---|---|
| 1 | OpenLibrary | `"key":"/works/OL1904498W"` → path `/works/OL1904498W.json` | **No** (`consumers=0`) | RC-2 discovery |
| 2 | PokeAPI | `"url":"https://…/pokemon/1/"` → **that absolute URL** is the next request | **No** (`consumers=0`) | RC-2 discovery |
| 3 | Wikipedia | `"pageid":6615610` → `?pageids=6615610` | **Yes** (`consumers=2`) | RC-1 classification |
| 4 | OpenFoodFacts | `"code":"3168930010265"` → path `/product/3168930010265` | **Yes** (`consumers=1`) | RC-1 classification |
| 5 | Nominatim | `"place_id":275905280` (array root) → `?place_id=…` | **Yes** (`consumers=1`) | RC-1 classification |
| 6 | reqres.in | `"id":3` → path `/users/3` | **No** (below length floor) | RC-3 threshold |

### Two distinct failure stages
* **Stage A — discovery (RC-2, apps 1–2).** The dependency never reaches the value model:
  `build_lineage` reports `consumers=0`. Whole-slot matching cannot equate a *composite path value*
  with individual path segments, nor an *absolute URL* with the request that uses it.
* **Stage B — classification (RC-1, apps 3–5).** Discovery **succeeds** (`consumers≥1`) and the value is
  then labelled `BUSINESS_MASTER_DATA` because its producer was a GET. `correlate/decide.py:118`
  accepts only `RUNTIME_GENERATED`, so the proven dependency is discarded.

This ordering matters for sequencing any fix: **changing the classification policy alone would still
leave apps 1 and 2 broken**, because their dependency is invisible one layer earlier.

## 3. Why synthetic fixtures score so differently

The 56 synthetic fixtures produce 94 correlations. Inspecting their construction, their producers are
overwhelmingly **POST/PUT create** calls, `Set-Cookie`, redirect `Location` headers, or auth token
issuance — all of which land in `RUNTIME_GENERATED` branches. Almost none of them model the
**GET search → GET detail** journey, which is the dominant shape in the six real applications.

> The fixture corpus encodes the same assumption as the engine (dynamic values are *created* by writes),
> so it cannot expose the engine's blind spot. That is why 94-vs-0 is not a contradiction: the two
> corpora are testing different worlds.

## 4. What the engine demonstrably does well

Verified by targeted probes against the current build (not fixtures):

| Capability | Status |
|---|---|
| Producer/consumer **field names differ** (`abc` → `verification`) | Works — matching is by value, not name |
| JWT / Base64 / UUID / hex / opaque tokens | Works, when server-**created** |
| Response body → URL path / query / header | Works, when server-**created** |
| Nested JSON, array members | Works |
| URL-encoded downstream value | Works (`_norm` unquotes) |
| Multiple consumers → one extractor | Works |
| Multiple producers → earliest chosen | Works |
| Value embedded in a larger string / prose | Works (boundary extractor) |
| Extractor verification before emission | Works — a non-resolving extractor is dropped, literal kept |

So the engine is **not** name-dependent and **not** shape-dependent. Its single discriminator is
**how the value came into existence** (created-by-write vs returned-by-read), and that is precisely the
discriminator that misclassifies real search→detail journeys.

## 5. Evidence commands
```bash
# per-app lineage + verdict for the dependent value
PYTHONPATH=src python - <<'PY'
from pathlib import Path
from har2jmx.engine import analyze
from har2jmx.lineage import build_lineage
t={'app01_openlibrary_search_to_work':'/works/OL1904498W',
   'app02_wikipedia_search_to_article':'6615610',
   'app03_pokeapi_list_to_detail':'https://pokeapi.co/api/v2/pokemon/1/',
   'app04_openfoodfacts_search_to_product':'3168930010265',
   'app06_nominatim_search_to_details':'275905280'}
for s,v in t.items():
    r=analyze(Path(f'benchmark/normalized/{s}.har').read_bytes())
    f=build_lineage(r.capture).by_value(v); d=r.classification.by_value(v)
    print(s, 'consumers=', len(f.consumers) if f else None, '|', d.classification.value if d else None)
PY
```

## 6. Recommendation (sequenced)

1. **Extend discovery (RC-2)** — index the request's absolute URL and multi-segment path prefixes as
   consumer slots. Pure recall work; emission stays gated by extractor verification, so it cannot
   manufacture false correlations.
2. **Then revisit the GET-producer policy (RC-1)** — only for values with a *proven in-journey consumer*.
   This changes the frozen correlate-vs-parameterize boundary and needs an explicit product decision.
3. Re-run this benchmark; target is recall ≥ 5/5 (excluding the documented threshold case) with
   false correlations still at **0**.
