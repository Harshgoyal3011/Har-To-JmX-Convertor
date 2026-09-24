# Over-correlation audit — Azure AD B2C application

**No code changed.** Audit only, as instructed.

**Evidence source.** The server does not retain uploaded HARs, but it retains generated plans. Two runs
of this application exist, which gives a genuine before/after on *your own data*:

| Run | Time | Code | Samplers | Extractors |
|---|---|---|---|---|
| `har2jmx_be2859355d` | 14:47 | **before** Change 1 & 2 | 31 | **9** |
| `har2jmx_31e16f27db` | 15:18 | **after** Change 1 & 2 | 34 | **12** |

Producer→consumer chains below are read from the emitted JMX, not inferred.

---

## 1. Audit table

| Value | Producer | Consumer(s) | Runtime-generated? | Downstream dep? | Replay needs runtime value? | Recommended | Current | Reason |
|---|---|---|---|---|---|---|---|---|
| **X_CSRF_TOKEN** | #5 B2C signin page, regex `"csrf":"…"` | #7, #8, #9 | **YES** | YES | **YES** | **CORRELATE** | CORRELATE | Per-session anti-forgery token. A recorded value is rejected for any other session. |
| **tx** | #5 page blob, `"transId":"…"` | #8, #9 | **YES** | YES | **YES** | **CORRELATE** | CORRELATE | Per-session B2C transaction id; the SelfAsserted/confirmed calls are bound to it. |
| clientId | #3 `getAuthConfigurations` | #5, #14 authorize | no | yes | **no** | HARDCODE | CORRELATE | OAuth client registration constant. Identical for every user, session and run. |
| appId | #1 `assets/json/config/env-config.json` | 9 unrelated API calls | no | yes | **no** | HARDCODE | CORRELATE | Deployment constant read from a static front-end config file. |
| groupName | #1 env-config.json, `$..tenant` | #3 | no | yes | **no** | HARDCODE | CORRELATE | Tenant name; deployment constant. (Variable name also misleading — it extracts `tenant`.) |
| redirectUrl | #1 env-config.json | 8, incl. the **entire path** of #10 | no | yes | **no** | HARDCODE | CORRELATE | Configured base/redirect URL. |
| url | #5 page blob, `"remoteResource":"…"` | #6 (entire path), #7 | no | yes | **no** | HARDCODE | CORRELATE | Static CDN/resource URL inside the B2C config blob. |
| path | #5 page blob, `"tenant":"…"` | #7, #8, #9 as path prefix | no | yes | **no** | HARDCODE *(borderline)* | CORRELATE | B2C tenant/policy path — constant for this environment. |
| **path2** | #5 page blob, `"api":"…"` | **NONE** — `${path2}` appears **0 times** | n/a | **NO** | n/a | **REMOVE** | CORRELATE | **Dead extractor.** No consumer at all; it should never have shipped. |
| response_modes_supported_1 | #4 OIDC discovery `.well-known/openid-configuration` | #5 authorize | no | yes | **no** | HARDCODE | CORRELATE | OIDC metadata listing **supported capabilities**. The client *chooses* a mode; the server does not issue one. |
| response_types_supported_6 | #4 OIDC discovery | #14 authorize | no | yes | **no** | HARDCODE | CORRELATE | Same — a capability list, not a runtime value. |
| getcustomizationCode | #3 `getAuthConfigurations`, `$..statusCode` | #7 | no | **coincidental** | **no** | HARDCODE / EXCLUDE | CORRELATE | Extracts an **HTTP status code**. The reuse is almost certainly a coincidental value match. |
| redirectParam | — | — | — | — | — | *(not a correlation)* | CSV parameter | Not present in the JMX extractor set; it is a parameter, not an extractor. |

### Verdict
* **Genuinely necessary: 2** — `X_CSRF_TOKEN`, `tx`.
* **Over-correlations: 9** — `clientId`, `appId`, `groupName`, `redirectUrl`, `url`, `path`,
  `response_modes_supported_1`, `response_types_supported_6`, `getcustomizationCode`.
* **Dead extractor: 1** — `path2`.

An experienced PE scripting this B2C flow would extract **the CSRF token and the transaction id**, and
hardcode (or environment-parameterize) everything else.

---

## 2. Is this a regression from Change 1 / Change 2? **No — mostly pre-existing**

**9 of the 12 extractors were already present at 14:47**, before either change:
`X_CSRF_TOKEN, clientId, getcustomizationCode, path, path2, response_modes_supported_1,
response_types_supported_6, tx, url`.

Change 1 (noise) added exactly **3**: `appId`, `groupName`, `redirectUrl`. Path diff confirms why —
it newly admitted `/artai/assets/json/config/env-config.json`, a JSON document under `/assets/`.
That admission is *correct by the rule* (it is a real request the app makes, and it is JSON, not a
static asset), but its **contents are pure deployment configuration**, so every value it exposes became
a correlation candidate.

Change 2 (multi-segment) contributed **none** of these.

---

## 3. Why the engine selected them — and the responsible stage

Every over-correlation follows the same path:

```
config document / discovery document / page config blob   (a RESPONSE)
        ↓  value genuinely appears later
later request consumes the same literal
        ↓
classify_values: producer is a GET, has consumers, not an entity id, not a catalog code
        ↓
RUNTIME_GENERATED  →  build_correlations accepts it  →  extractor emitted
```

**Primary stage: CLASSIFICATION.**
`classify/value_engine.py` — the GET-producer promotion (`if consumers and not is_id and not
catalog_code: → RUNTIME_GENERATED`). This is the change that fixed search→detail recall. It asks
*"was it produced by a response and consumed later?"* but **not** *"is it static application or
protocol configuration?"* A config endpoint's response satisfies the first question perfectly.

**Secondary stage: DISCOVERY.** Change 1 widened the input by admitting a static front-end config
document. The noise rule is behaving correctly; the problem is what classification then does with it.

**Not implicated:** VALIDATION (every extractor verified against its response — they resolve
correctly), and the values *are* genuinely present downstream, so this is not a matching error.

**Separate defect — NECESSITY / EMISSION:** `path2` shipped with **zero** consumers. Worse, the
production path never checks: `server/handler.py` calls `emit_jmx`, and `emit_jmx` builds the plan but
**never calls `validate_plan`**. The materialization audit therefore runs only in tests and the
benchmark — it is not enforced in the product. That is why a dead extractor reached your plan.

---

## 4. Why the 44-workflow corpus did not catch this

The corpus contains no application that serves a **configuration document** (`env-config.json`,
`.well-known/openid-configuration`, an embedded page config blob) and then consumes those constants.
Precision measured 1.000 because every corpus producer emits genuine per-run state. This B2C capture is
the first real evidence of the *static-configuration* failure mode, and it is a **class**, not a
one-off: any SPA with a bootstrap config endpoint plus OIDC discovery will reproduce it.

---

## 5. Proposed smallest safe changes — NOT implemented, for your decision

**A. Enforce the materialization audit in the product (low risk, no policy change).**
Have `emit_jmx` run `validate_plan`/`audit_materialization` and drop or flag any correlation whose
variable is never referenced. Fixes the `path2` class outright and makes the guarantee the benchmark
measures actually apply to what users download. This changes no correlation policy.

**B. The static-configuration problem is genuinely hard from ONE capture.**
`clientId` and `X_CSRF_TOKEN` are structurally identical in a single HAR: both first appear in a
response and are both consumed later. Honest options:

1. *Multi-run as a NEGATIVE signal only.* Two captures separate them immediately: `csrf`/`transId`
   change, while `appId`/`clientId`/`tenant`/`redirectUrl`/`response_*_supported` are byte-identical.
   **This is a correction to my earlier recommendation**: I argued multi-run cannot distinguish
   server-generated from user input (true — `firstname` varies too). But it *does* distinguish
   **constant configuration** from **per-session state**, which is exactly this defect. Used only to
   *suppress* (never to trigger), it cannot create a false correlation. Cost: requires 2+ HARs.
2. *Session-scope evidence in the existing promotion.* Promote a GET-produced value only when its
   producing response is part of the session-bearing journey (sets/uses a session or auth artefact),
   rather than a pre-session bootstrap fetch. `env-config.json` and `.well-known/openid-configuration`
   are fetched before any session exists; the B2C signin page that mints `csrf`/`transId` is not.
   ⚠ This narrows the promotion you froze, and must be measured against the 44-workflow corpus —
   it risks the recall that promotion bought (0.842 → 0.923).
3. *Route this class to REVIEW rather than CORRELATE.* Preserves precision at the cost of recall and
   adds manual work.

**I recommend A now** (it is safe, fixes a real defect, and is policy-neutral), and a decision from you
on B before touching classification. I have deliberately not implemented any of it.

**Explicitly rejected:** field-name blacklists (`clientId`, `path`, `url`, `response_*_supported`),
length/entropy rules, and per-application exceptions.
