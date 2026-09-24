# Parameterization & CSV Analysis — Real Applications

Quality metric applied (per brief): **fewest unnecessary columns while capturing every meaningful
business input** — not maximum coverage.

## 1. Scores

| Metric | Value |
|---|---|
| Real applications scored | 6 |
| CSV columns produced (total) | 13 |
| Columns that are genuine business inputs | **6** |
| **Unnecessary columns** | **7 (54%)** |
| Missed business parameters | 2 |
| Dependent server values miscast as parameters | 3 |

**More than half of all CSV columns generated across real applications do not belong there.**

## 2. Per application

| App | Produced CSV | Correct | Unnecessary | Missed | Assessment |
|---|---|---|---|---|---|
| OpenLibrary | `q`, `donation_identifier`, `action_name`, `pv_id` | `q` | `donation_identifier`, `action_name`, `pv_id` | — | **FAIL** — 3/4 junk |
| Wikipedia | `pageid`, `srsearch` | `srsearch` | `pageid` (dependent value) | — | **FAIL** — dependency miscast |
| PokeAPI | — | — | — | — | PASS (nothing to vary) |
| OpenFoodFacts | `code` | — | `code` (dependent value) | `categories_tags_en` | **FAIL** — miscast + missed input |
| reqres.in | — | — | — | — | PASS (`page`/`per_page` correctly left as config) |
| Nominatim | `place_id`, `name` | — | `place_id` (dependent), `name` (response echo) | `q` | **FAIL** — miscast + missed input |

## 3. The two failure classes

### Class A — telemetry parameters (OpenLibrary, 3 columns)
`action_name` and `pv_id` are Matomo analytics fields; `donation_identifier` comes from a third-party
donation iframe. They are only candidates because those three requests were **retained as business
traffic** (DEF-004). The parameterizer behaved reasonably given its input — the defect is upstream in
noise classification.

> Fixing noise classification removes 3 of the 7 unnecessary columns with no change to the
> parameterization layer at all.

This is a *different* class from the W3C Navigation-Timing metrics (`fetchStart`, `domComplete`,
`duration`, `transferSize`) which the engine already excludes correctly — those never appeared in any
real-app CSV here. Vendor analytics **query parameters** are the remaining gap.

### Class B — dependent server values (Wikipedia, OpenFoodFacts, Nominatim, 3 columns)
`pageid`, `code` and `place_id` are the server's *answer* to a search, consumed by the very next
request. Emitting them as single-row CSV columns is a correctness defect, not a tidiness issue:

* The plan looks parameterised and passes `validate_plan`.
* Every virtual user sends the same captured id.
* The search response is computed and then discarded — the journey no longer tests its own dependency.
* The script breaks as soon as the backing dataset changes.

A single-row CSV column is functionally a hardcoded value with extra ceremony.

### Missed business inputs (2)
`categories_tags_en` (OpenFoodFacts category filter) and `q` (Nominatim place query) are exactly the
values a PE *would* vary per virtual user, and neither became a parameter — while the server-issued id
next to them did. The selection is close to **inverted** on those two apps.

## 4. What the parameterizer gets right

| Behaviour | Evidence |
|---|---|
| Search terms recognised as business inputs | `q` (OpenLibrary), `srsearch` (Wikipedia) |
| Fixed request configuration left hardcoded | `limit`, `offset`, `page`, `per_page`, `format`, `fields` never parameterised |
| W3C browser-timing telemetry excluded | no `fetchStart`/`domComplete`/`transferSize` column in any real-app CSV |
| CSV is usage-gated | every emitted column is referenced by a `${var}` in the JMX |
| No credential leakage | no captured secret written to CSV (no login flows in this corpus) |

## 5. Recommendation

1. **Fix noise classification first** (DEF-004). Highest ratio of benefit to risk: removes 3 of 7
   unnecessary columns without touching parameterization logic.
2. **Never parameterize a value with a proven in-journey downstream consumer** (DEF-003). Even if the
   correlate-vs-parameterize policy is left unchanged, this guard alone prevents the false-green:
   such a value should be correlated, or left literal and flagged for review — never a single-row column.
3. **Improve business-input recall for filter/query parameters** (`categories_tags_en`, `q`) — these are
   the scenario inputs a PE varies. Note the brief's constraint: no field-name lists; the usable
   structural signal is *client-supplied query parameter on a search/list endpoint that is not echoed
   back as a server-issued id*.

## 6. Evidence
```bash
PYTHONPATH=src python benchmark/expected/ground_truth.py   # -> CORRELATION_SCORE.json (also scores params)
```
Row fields `missed_parameters`, `unnecessary_parameters` and `miscast_as_parameter` back every number above.
