# Corpus Manifest & BLOCKED Register

## A. Applications genuinely captured (REAL)

| ID | Application | Domain | Business flow | Source | Reqs | Hosts | Capture notes |
|---|---|---|---|---|---|---|---|
| APP01 | OpenLibrary | Library / public catalogue | search books → open work → list editions | openlibrary.org (public, no login) | 51 | 6 | Full browser capture: static assets, Sentry, Matomo, athena pageview beacon, donate iframe, third-party covers CDN |
| APP02 | Wikipedia | Knowledge / media | search articles → article info by pageid → article extract | en.wikipedia.org (public, MediaWiki API) | 28 | 2 | Full browser capture incl. first-party EventLogging beacon and 200 KB `load.php` bundles |
| APP03 | PokeAPI | Media / gaming catalogue | list resources → open resource by returned URL | pokeapi.co (public) | 2 | 1 | API-only journey (service has no UI) |
| APP04 | OpenFoodFacts | Retail / food | search by category → open product by returned code | world.openfoodfacts.org (public) | 2 | 1 | API-only journey |
| APP05 | reqres.in | SaaS / demo REST | list users → open user by returned id | reqres.in (public demo API) | 2 | 1 | API-only journey; dependent id is a single digit |
| APP06 | Nominatim (OSM) | Geo / logistics | search place → place details by returned place_id | nominatim.openstreetmap.org (public) | 2 | 1 | API-only journey |

**Capture method.** Traffic observed in the Claude browser pane via the Resource Timing API plus live
`fetch` responses from the same public endpoints. Every URL, status, timing and body originates from a
real response.

**Disclosed transformations** (see each HAR's `log.comment`):
* APP01 only: the API journey was issued ~218 s after page load due to interactive instrumentation; that
  inter-phase gap is compressed to a 4 s think time. Timings *within* each phase are untouched. Duplicate
  instrumentation probes dropped. `benchmark/raw/` retains the original offsets.
* HTML document bodies are not retained (size). API response bodies are verbatim, capped at 200 000 chars;
  any capped entry is marked `_truncatedBody`. Journeys were limited to steps whose **producer** body was
  captured complete, so the converter is never penalised for harness truncation.

## B. BLOCKED — could not be captured, not faked

| Domain | Representative app | Reason | Substitute used |
|---|---|---|---|
| E-commerce (full cart/checkout) | demo.opencart.com | **Cloudflare anti-bot interstitial.** Not bypassed — the brief forbids it and so do my operating rules. | OpenFoodFacts (retail/food, no login) |
| Banking / Finance | parabank & similar demos | **Login required.** I am not permitted to enter passwords, including published demo credentials. | SYNTHETIC `complex_banking.har` (labelled) |
| Healthcare | patient-portal demos | Login required | SYNTHETIC `complex_healthcare.har` (labelled) |
| Insurance | policy/claims portals | Login required | SYNTHETIC `complex_upload.har` (claims, labelled) |
| CRM | SuiteCRM / Vtiger demos | Login required | SYNTHETIC `sample_user_scoped.har` (labelled) |
| ERP / Manufacturing | ERPNext / Odoo demos | Login required | SYNTHETIC `soap_session.har` (labelled) |
| Telecom, Travel/Booking, Job portals, Ticketing, Government services, Real estate, Food delivery, Education | various | Either login-gated, anti-bot protected, or ToS-restricted for automated capture | Partially covered by SYNTHETIC fixtures; **no real capture claimed** |

> Consequence to keep in mind when reading the results: the real bucket is **read-heavy and
> unauthenticated**. It contains no login, no CSRF token, no session cookie and no POST-create journey.
> The engine's strongest correlation paths (auth tokens, `Set-Cookie`, redirect `Location`, POST-created
> ids) are therefore **under-represented in the real bucket and over-represented in the synthetic one**.
> Both facts are stated rather than averaged away.

## C. Pre-existing corpus (not captured by this benchmark)

| Bucket | n | Description |
|---|---|---|
| `REAL_API` | 11 | Hand-authored probes against **real** public API hosts (dummyjson, fakestore, restful-booker, petstore3, gorest, swapi, rickandmorty, restcountries, jsonplaceholder, Platzi, openlibrary). 2–6 entries each, single host. |
| `SYNTHETIC` | 56 | Hand-authored fixtures on `*.example.com` covering banking, healthcare, OAuth, SAML, SOAP, CSRF rotation, pagination, refresh, upload, logout, etc. |

Neither set contains a browser capture: no static assets, no third-party hosts, no analytics beacons.

## D. Directory layout

```
benchmark/
  raw/                     untouched capture records (rows + real response bodies)
  normalized/              evaluation HARs built from raw/ (this is what the converter is run against)
  expected/ground_truth.py hand-labelled expected correlations/parameters + scorer
  RAW_RESULTS/             one JSON per HAR: full Phase-3 metrics
  capture/                 capture → HAR builders (har_builder.py, build_from_capture.py, appNN_*.py)
  run_baseline.py          Phase-3 runner
  APPLICATION_SCORECARD.csv
  CORRELATION_SCORE.json
  BASELINE_REPORT.md  DEFECT_REGISTER.md  CORRELATION_ANALYSIS.md  PARAMETERIZATION_ANALYSIS.md
```

## E. Reuse as a regression corpus

```bash
python benchmark/capture/app01_openlibrary.py
python benchmark/capture/app02_wikipedia.py
python benchmark/capture/apps03_06_api_journeys.py
python benchmark/run_baseline.py
PYTHONPATH=src python benchmark/expected/ground_truth.py
```
The HARs are deterministic once built, so `CORRELATION_SCORE.json` is a stable regression signal:
today's baseline is **recall 0/6, false correlations 0**. Any correlation work should move recall up
while holding false correlations at 0.
