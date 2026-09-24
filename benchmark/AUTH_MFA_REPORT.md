# Authentication & MFA Analysis (Parts 4, 5, 11) + BLOCKED register

Engine frozen for this evaluation — the only code changes in this phase were RC-A and RC-D (Part 1),
applied and verified *before* capture. Suite 539 passed; 96 HARs, 100% conversion, 0 crashes.

---

## 1. Authentication workflows captured (all REAL)

| App | Domain | Auth pattern | Producer → consumer |
|---|---|---|---|
| **Quotes to Scrape** | Generic web / auth sandbox | C/D form-urlencoded login + **K/L CSRF token** | `csrf_token` (HTML hidden input) → form-urlencoded body |
| **Platzi Fake Store API** | E-commerce / SaaS | **B** email+password, **E** JSON login, **G** token → header | `access_token` (JSON) → `Authorization: Bearer` |
| **DummyJSON** | SaaS / commerce | **A** username+password, **I** refresh token → next token | `refreshToken` → refresh **body**; new `accessToken` → `Authorization` |

### Results — every one correct

| App | Server value | Correlated | Verified | **Materialized** | Credentials parameterized |
|---|---|---|---|---|---|
| Quotes | `csrf_token` | ✅ | ✅ | ✅ | `username`, `password` ✅ |
| Platzi | `access_token` | ✅ | ✅ | ✅ | `email`, `password` ✅ |
| DummyJSON | `refreshToken` | ✅ | ✅ | ✅ | `username`, `password` ✅ |
| DummyJSON | `accessToken` (post-refresh) | ✅ | ✅ | ✅ | — |

**Correlation/parameterization split is exactly right in all three.** The engine put the *server's*
values through extractors and the *user's* values into the CSV — with no domain rules and no knowledge
that these were login flows.

### True negatives — equally important, all correct

| Value | Why it must NOT correlate | Correlated? |
|---|---|---|
| Platzi `refresh_token` | returned by login but never consumed downstream in this capture | **No** ✅ |
| DummyJSON first `accessToken` | superseded by the refresh; never used | **No** ✅ |
| `password` (both apps) | user input, not server-generated | **No** ✅ |

The superseded-token case is the sharpest one: a naive engine would correlate *both* access tokens. It
correlated only the one the authenticated call actually uses.

### Part 11 — end-to-end auth chain validity
For DummyJSON the full chain is represented in the generated JMX:

```
login (username/password from CSV)
  └─ extractor → ${refreshToken}
       └─ POST /auth/refresh  body uses ${refreshToken}
            └─ extractor → ${accessToken}
                 └─ GET /auth/me   Authorization: Bearer ${accessToken}
```
No hardcoded token remains; `validate_plan` is clean. None of the failure modes the brief listed
occurred (token left hardcoded, password correlated, challenge id hardcoded).

### One capture flaw of mine, corrected
My first Quotes capture used the *same* string for username and password, so they collapsed into one
lineage flow and the CSV showed a single column. That was a **capture artifact, not an engine defect** —
re-captured with distinct values, both `username` and `password` parameterize correctly. Recorded here
rather than quietly fixed.

---

## 2. MFA / OTP (Part 5) — **BLOCKED**

**No MFA workflow was captured, and none is claimed.**

| Requirement | Status | Reason |
|---|---|---|
| A login → MFA challenge | **BLOCKED** | no public sandbox exposes a capturable challenge |
| B challenge/transaction id | **BLOCKED** | same |
| C challenge id → OTP verification | **BLOCKED** | same |
| D OTP input → parameterization | **BLOCKED** | same |
| E challenge token → correlation | **BLOCKED** | same |
| F MFA session cookie | **BLOCKED** | same |
| G auth state → downstream | **BLOCKED** | same |

**Why.** Every legitimate MFA flow needs either (a) a real account with a second factor — which would
mean handling someone's credentials and security controls, or (b) a self-hosted IdP (Keycloak/Authentik)
where I would have to **create a user account**, which I am not permitted to do. Public API sandboxes
(DummyJSON, Platzi, restful-booker, reqres) implement single-factor auth only; none exposes an OTP or
challenge endpoint. I searched for a documented fixed-OTP sandbox and found none.

**What I did NOT do:** fabricate an MFA HAR, or author a synthetic MFA fixture and count it as a real
application. A synthetic MFA fixture could be added *clearly labelled* if you want the shape exercised —
say the word — but it would prove the engine handles a shape I invented, not a real application.

---

## 3. BLOCKED register — domains

| Domain | Status | Reason | Substitute used |
|---|---|---|---|
| Insurance | **BLOCKED** | no public no-login API/portal; all quote/claims systems are gated | labelled SYNTHETIC fixtures only |
| CRM | **BLOCKED** | SuiteCRM/Vtiger demos require login | labelled SYNTHETIC only |
| ERP / Manufacturing | **BLOCKED** | ERPNext/Odoo demos require login | labelled SYNTHETIC only |
| Banking | **BLOCKED** | Open-Banking sandboxes require registration + client credentials | CoinGecko/Frankfurter (finance-adjacent) where captured |
| Telecom | **BLOCKED** | number/coverage APIs require API keys | — |
| Real estate | **BLOCKED** | property APIs require API keys | — |
| Ticketing / events | **BLOCKED** | Ticketmaster/SeatGeek require API keys | Deck of Cards / Open Trivia (booking-shaped) |
| Food delivery | partial | no public ordering API; catalogue only | OpenFoodFacts, TheMealDB |
| E-commerce (full checkout) | **BLOCKED** | demo.opencart.com sits behind Cloudflare anti-bot — **not bypassed** | Platzi, DummyJSON |
| Healthcare | **COVERED** | HAPI FHIR public R4 test server | — |
| Government | **COVERED** | ClinicalTrials.gov, GBIF | — |
| AI / GenAI | **not yet captured** | candidate: Hugging Face Hub API (public, no login) | — |

Nothing here was bypassed: no CAPTCHA solved, no anti-bot evaded, no account created, no real
credentials used. Only credentials published by a sandbox *as its documented public entry point*.

---

## 4. Corpus status

| Bucket | HARs | Correlations |
|---|---|---|
| REAL_CAPTURE (full browser) | 2 | 2 |
| REAL_API_JOURNEY | 27 | 23 |
| REAL_API (pre-existing probes) | 11 | 8 |
| SYNTHETIC (labelled) | 56 | 96 |
| **Total** | **96** | 100% conversion, 0 crashes |

29 real workflows now exist (26 previously scored + 3 new authentication workflows).
