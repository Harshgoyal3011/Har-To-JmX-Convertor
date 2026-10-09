# HAR-to-JMeter converter: repository code review

Reviewed: **5 October 2026**<br>
Repository commit: **`69bc53cd12dca4ce1eb6c5b7203a6b22d5f2b9a2`**<br>
Review type: repository-wide assessment, source inspection, fresh regression execution, synthetic defect probes, and comparison with existing benchmark reports.

## Assessment

The converter has a useful compiler-style pipeline and broad regression coverage. The recent authentication, redirect, content-retention, multipart, variable-ownership, and workflow fixes improve it substantially. However, generated XML can load successfully while reconstructing the wrong HTTP requests or using the wrong runtime values. The remaining defects below prevent a blanket claim that every generated plan is ready for load testing.

The strongest reproduced warning is `sample_list_id.har`: it reports **readiness 100, replay passed, and no static-validator issues**, while its required `orderId` extractor is unresolved, the consumer keeps a recorded literal, and the JMX comment contains no manual-work warning.

No production code was modified for this review. The Markdown report is the only intentional repository change. Synthetic outputs, reproducible probes, inventory, and validation results are stored separately in [`../../code-review-20261005/`](../../code-review-20261005/).

## Scope and validation

The inventory covers **179 files**: 50 package Python files, 42 test/support Python files, one deployment script, three browser assets, ten Markdown documents, configuration/deployment files, and 68 HAR samples containing 284 requests. Package initializers, shared patterns/utilities, test collection, examples, and fixture boundaries were included. Generated output, dependency installations, Git internals, and historical engine snapshots are not part of the reviewed application. See [the file and hash inventory](../../code-review-20261005/inventory.json).

This is a repository-wide module review, not a guarantee of exhaustive path coverage. Tests were executed in full; targeted test-source inspection focused on defect assertions, integration coverage, and recent changes. Historical external benchmark evidence is explicitly identified below and was not rerun as part of this review.

| Check | Fresh result | Practical meaning |
|---|---|---|
| Full pytest suite, Python 3.14 | **481 passed**, 9.94 seconds | Current regressions pass; [JUnit evidence](../../code-review-20261005/pytest-final.xml). |
| Source deployment smoke | **Passed** | Service starts, honors platform PORT, and serves health/UI/assets. |
| Synthetic defect probes | **Completed** | Local reproductions described below; [results](../../code-review-20261005/reproductions.json), [probe script](../../code-review-20261005/reproduce_findings.py). |
| Ruff, existing effective configuration | **57 findings** | Mostly style, modernization, and broad exception handling; [machine-readable output](../../code-review-20261005/ruff.json). |
| Ruff isolated default rules | **64 findings** | Rule selection differs from inherited configuration; counts are not directly comparable. |
| Explicit isolated E4/E7/E9/F rules | **13 findings** | Semicolon style, ambiguous local names, and a lambda assignment. |
| Python AST parsing and HAR JSON parsing | **Passed for inventoried files** | Syntax/sample consistency, not replay correctness. |
| mypy | **Not run** | The module was not available in the existing dependency installation. |
| Browser interaction/accessibility | **Source inspected; no browser run** | No visual or assistive-technology pass is claimed. |
| Actual JMeter HTTP replay | **Not run** | No live business execution or concurrent-load success is claimed. |

The first pytest attempt had 476 passes and five fixture setup errors because the review output parent directory did not yet exist. After the directory existed, a fresh full run passed all 481 tests. Those initial errors were review setup errors, not application defects.

Evidence labels used below:

- **Reproduced:** observed in fresh local probes against the reviewed commit. Some probes deliberately isolate an internal stage; that scope is stated.
- **Source-confirmed:** a concrete behavior follows from the code, but its full operational failure was not executed.
- **Risk/limitation:** depends on deployment, workload, or missing capture evidence; not claimed as an observed incident.
- **Historical evidence:** measured by existing workspace reports, not newly measured here.

## Prioritized findings

P1 means incorrect replay, hidden failure, credential scope expansion, or service availability exposure worth addressing before trusting unattended/shared use. P2 means material correctness, usability, maintainability, or coverage problems. Priorities do not imply every capture is affected.

| ID | Priority | Finding | Evidence |
|---|---|---|---|
| R01 | P1 | Raw-body requests lose URL query parameters | Reproduced |
| R02 | P1 | POST form requests move URL query parameters into body arguments | Source-confirmed; emitted representation reproduced |
| R03 | P1 | Parameterized numeric JSON changes type | Reproduced |
| R04 | P1 | Runtime substitutions are not escaped for JSON/XML | JSON reproduced; XML source-confirmed |
| R05 | P1 | Equal literals collapse independent runtime identities | Lineage/substitution stages reproduced |
| R06 | P1 | Readiness and JMX warnings omit failed required extraction | Reproduced end to end |
| R07 | P1 | High-confidence non-auth extractors omit runtime health checks | Reproduced emitted plan |
| R08 | P1 | UUID-shaped hidden CSRF tokens are rejected as configuration | Reproduced end to end |
| R09 | P1 | Common-header hoisting expands credential/header scope | Hoisting reproduced; scope source-confirmed |
| R10 | P1 | State-setting/static and download requests can be excluded | State-setting static/HEAD reproduced |
| R11 | P1 | Refresh retry matching removes unrelated failures | Reproduced |
| R12 | P1 | Automatic CSV synthesis invents invalid constrained inputs | Reproduced synthesis stage |
| R13 | P1 | Concurrent upload memory/work is not bounded in aggregate | Source-confirmed availability risk |
| R14 | P2 | JSONPath construction loses literal key boundaries | Reproduced expression construction |
| R15 | P2 | Traversal limits hide producers and undermine uniqueness | Missing producer reproduced |
| R16 | P2 | One logical UUID becomes independent values at each occurrence | Emitted expressions reproduced |
| R17 | P2 | Valid `null` JSON and unparseable JSON bodies disappear | Reproduced sampler emission |
| R18 | P2 | Malformed HAR containers return internal errors; empty capture passes | Reproduced analysis behavior |
| R19 | P2 | Pruning races conversion and download operations | Source-confirmed concurrency risk |
| R20 | P2 | UI hides review/uncertainty and disagrees with emitted artifacts | Row mismatch reproduced; omissions source-confirmed |
| R21 | P2 | Default installed output path may be unwritable | Source-confirmed installation risk |
| R22 | P2 | Related CSV files lack a joint allocation policy | Source-confirmed multi-user risk |
| R23 | P2 | Pacing is inferred from request starts and parallel traffic is serialized | Source-confirmed modeling limitation |
| R24 | P2 | Shared deployment exposes package files and bearer-style downloads | Source routes reproduced; ownership limitation source-confirmed |

### R01 — Raw-body requests lose URL query parameters

**Location:** [emit/jmx.py:302](../src/har2jmx/emit/jmx.py#L302), [emit/jmx.py:320](../src/har2jmx/emit/jmx.py#L320), [emit/jmx.py:357](../src/har2jmx/emit/jmx.py#L357).

`POST https://example.test/api/orders?tenant=acme` with `{"qty":3}` emits path `/api/orders` and only the raw JSON argument. Query argument generation is inside the alternative to the raw-body branch, and the normal sampler path has no query suffix. JSON, GraphQL, SOAP, XML, and text bodies are affected when present.

**Impact:** tenant selection, filters, API versions, and routing parameters disappear.

**Repair:** render the encoded URL query independently of body construction. Keep raw/form/multipart data exclusively in its intended body representation. Verify actual HTTP URL and body independently for GET, POST, PUT, and PATCH.

### R02 — Form-body requests do not preserve query/body separation

**Location:** [emit/jmx.py:326](../src/har2jmx/emit/jmx.py#L326).

The non-raw branch combines `request.query` and form fields into one `HTTPsampler.Arguments` collection, while the path contains no query. The probe for `POST /api/data?tenant=acme` with `name=Alice` emits both `tenant` and `name` as regular arguments. JMeter's normal form POST sends these arguments in the request body.

**Impact:** a server reading `tenant` from the URL receives a different request. Multipart requests have the same conceptual separation problem and need independent wire verification.

**Repair:** place recorded query data in the sampler URL and reserve form arguments for the body. Validate with a local HTTP receiver; this review reproduced the JMX representation, not a live JMeter wire request.

### R03 — Numeric JSON replacements become strings

**Location:** [emit/jmx.py:220](../src/har2jmx/emit/jmx.py#L220), [emit/jmx.py:309](../src/har2jmx/emit/jmx.py#L309).

`_sub_json()` returns replacement expressions as strings; `json.dumps()` then quotes them. A body with integer `qty` and floating-point `amount` becomes `{"qty":"${qty}","amount":"${amount}"}`. Resolving values to 7 and 2.5 still produces strings.

**Impact:** strict APIs reject the body or execute different comparison/calculation behavior.

**Repair:** use typed template nodes or a runtime serializer that preserves the original JSON type. Define behavior for invalid numeric CSV values and verify parsed runtime bodies. Presence of `${qty}` alone is insufficient validation.

### R04 — Runtime strings are not escaped for their destination

**Location:** [emit/jmx.py:220](../src/har2jmx/emit/jmx.py#L220), [emit/jmx.py:271](../src/har2jmx/emit/jmx.py#L271).

The serializer escapes the placeholder, not the future value. `{"name":"${name}"}` with runtime value `A"B` becomes invalid JSON. Backslashes and newlines can also change the body. XML/SOAP substitutions insert runtime text directly without XML escaping.

**Impact:** perfectly valid input data can generate malformed requests or alter body structure.

**Repair:** serialize resolved structured values at runtime using JSON/XML rules. Treat intentionally raw markup separately. Add meaningful quote, slash, newline, Unicode, ampersand, and angle-bracket cases.

### R05 — Equal captured literals merge unrelated identities

**Location:** [lineage/graph.py:345](../src/har2jmx/lineage/graph.py#L345), [emit/jmx.py:176](../src/har2jmx/emit/jmx.py#L176), [emit/jmx.py:119](../src/har2jmx/emit/jmx.py#L119).

Lineage is keyed by normalized value and chooses the earliest response producer. An order response with `orderId=1001` and an unrelated other-host account request with `accountId=1001` become one flow. The isolated substitution stage then turns the unrelated account ID into `${orderId}`.

Normalization also merges whitespace/type/URL-encoded variants; JSON array positions are omitted. The P2-3 variable ownership fix protects CSV names and approved CSV request slots, but the runtime literal-to-variable map still applies globally.

**Impact:** unrelated IDs, reissued equal tokens, list positions, and different hosts can inherit the wrong runtime value.

**Repair:** model producer events and individual consumer occurrences explicitly, including host, request index, location segments, array index, original type, and transform. Equality should suggest an edge, not establish identity. Substitute only approved occurrences.

### R06 — Readiness passes before final extraction feasibility is known

**Location:** [engine.py:120](../src/har2jmx/engine.py#L120), [emit/jmx.py:728](../src/har2jmx/emit/jmx.py#L728), [emit/validate.py:89](../src/har2jmx/emit/validate.py#L89).

Replay validation runs before extractor verification and is not reconciled after emission. The JMX warning counts only `classification.needs_correlation()`. The static validator intentionally exempts unresolved extractor literals.

**Fresh reproduction:** `sample_list_id.har` reports readiness **100**, `passed=True`, `validate_plan=[]`, unresolved `orderId`, and comment `Generated by har2jmx from a HAR capture.` The bundled/manual UI list does report the unresolved value, but the readiness badge and plan comment contradict it.

**Impact:** users can trust a passing indicator while replay still requires manual repair.

**Repair:** derive readiness and warnings from a final emission manifest. Required unresolved dependencies should block readiness. Distinguish analysis complete, structurally valid, requires review, and runtime verified. Do not define an empty static issue list as production-clean.

### R07 — Recorded confidence suppresses runtime health assertions

**Location:** [emit/jmx.py:805](../src/har2jmx/emit/jmx.py#L805), [tests/test_extractor_verify.py:24](../tests/test_extractor_verify.py#L24).

`UNIQUE` plus `High` confidence suppresses the correlation-health assertion. `sample_flow.har` emits its `orderId` extractor without `Assert orderId correlated`; the test explicitly expects this omission. An HTTP 200 error response during execution can omit the ID while passing the response-code assertion.

**Impact:** the source failure is hidden and later requests use `NOT_FOUND`. Confidence in the recording does not guarantee a future response.

**Repair:** guard every required runtime extraction and reset applicable variables before production. Authentication already has separate freshness/reset/stop-thread checks; preserve those and extend appropriate guarantees to required business state.

### R08 — UUID-shaped hidden CSRF tokens are rejected

**Location:** [correlate/necessity.py:143](../src/har2jmx/correlate/necessity.py#L143).

A hidden input/meta value containing a UUID and no more than 40 characters is rejected as a stable app identifier before credential-consumer evidence is considered.

**Fresh reproduction:** a UUID in hidden field `csrf`, later sent as `X-CSRF-Token`, is rejected as `configuration`; `${csrf}` is absent from the plan.

**Impact:** every virtual user reuses captured security state and requests fail.

**Repair:** let lifecycle and credential-consumer evidence override shape heuristics. When stability cannot be established, report uncertainty instead of asserting that all users share the value.

### R09 — Header hoisting broadens recorded scope

**Location:** [emit/jmx.py:547](../src/har2jmx/emit/jmx.py#L547), [emit/jmx.py:574](../src/har2jmx/emit/jmx.py#L574).

A same-valued header present on roughly 60% of requests is hoisted to thread-group scope. Only selected names, including `Authorization`, are excluded. `X-Api-Key` on two of three requests qualifies even when the third request is to another host and originally has no such header.

**Impact:** credentials/custom state can be sent to unintended hosts or before its producer. Ordinary request-dependent headers also change behavior.

**Repair:** hoist only headers with identical applicability across the exact host/controller scope. Keep credential/runtime headers on approved sampler occurrences. Verify both presence and absence.

### R10 — Early exclusions can remove required state or downloads

**Location:** [classify/request_noise.py:126](../src/har2jmx/classify/request_noise.py#L126), [classify/request_noise.py:208](../src/har2jmx/classify/request_noise.py#L208).

Static path/extension checks run before auth and attachment roles. The cookie protection in the MIME fallback does not protect the earlier extension/path branches. A `/static/state.js` response setting `SID` is still excluded. All HEAD requests are excluded, including a HEAD response that initializes a session. `.pdf`/`.zip` attachment downloads also match static extensions before download detection.

**Impact:** session initialization, required response state, and business download actions disappear from replay.

**Repair:** classify initial candidates, then reconcile exclusions with required producer/dependency and attachment evidence. Keep business HEAD/OPTIONS uses when evidenced; do not assume method alone proves noise.

### R11 — Refresh recovery matches unrelated requests

**Location:** [classify/request_noise.py:293](../src/har2jmx/classify/request_noise.py#L293).

The algorithm searches arbitrarily far ahead for a refresh and a successful retry matching only method/path. It ignores origin, query, body, and session boundaries.

**Fresh reproduction:** failed `https://a.test/api/item?item=one` is excluded after a refresh followed by successful `https://b.test/api/item?item=two`.

**Impact:** an unrecovered business failure is silently removed, producing misleading traffic and results.

**Repair:** require a bounded, same-session recovery sequence and equivalent request semantics apart from the changed credential. Preserve uncertain failures for review.

### R12 — Synthetic rows violate business constraints

**Location:** [emit/jmx.py:890](../src/har2jmx/emit/jmx.py#L890), [emit/jmx.py:919](../src/har2jmx/emit/jmx.py#L919).

Automatic synthesis treats non-credential/non-ID text and numbers as safe to vary by suffix/increment. The probe produces `USD2`, `USD3`, and latitude `91` from `USD` and `89`. Date increments can also break journey relationships or validity windows.

**Impact:** the generated workload contains invalid data even if the captured row was valid. False failures and unintended scenario changes follow.

**Repair:** make synthesis an explicit policy with constraints and provenance. Default constrained enums, catalog selections, bounded numbers, credentials, and related dates to observed/supplied rows. Report generated rows separately. The 200-row synthesis cap and 2,000-thread UI limit must not imply 2,000 distinct identities.

### R13 — Upload resource bounds are per request, not per service

**Location:** [server/handler.py:116](../src/har2jmx/server/handler.py#L116), [server/handler.py:211](../src/har2jmx/server/handler.py#L211), [server/multipart.py:10](../src/har2jmx/server/multipart.py#L10), [render.yaml](../render.yaml).

`ThreadingHTTPServer` accepts concurrent handlers. Each can read up to 250 MB, build another MIME input buffer, parse JSON, construct analysis structures, and compress artifacts. There is no conversion-worker semaphore, aggregate budget, or socket read timeout configured. Negative `Content-Length` is also accepted and reaches `read(-1)`, which reads until EOF instead of a bounded declared length.

**Impact:** a few simultaneous large uploads can exhaust memory or occupy workers. This matters because the supplied deployment binds to `0.0.0.0` and exposes a public service. No resource-exhaustion stress test was performed.

**Repair:** validate nonnegative lengths/framing, bound concurrent conversion work, use upload/read deadlines and total resource budgets, and spool/stream large inputs where practical. Set service-appropriate upload limits based on measured memory amplification.

### R14 — JSONPath generation loses literal keys

**Location:** [correlate/decide.py:64](../src/har2jmx/correlate/decide.py#L64), [validate/extractors.py:99](../src/har2jmx/validate/extractors.py#L99).

Paths are flattened to dotted strings and split at the final dot. Literal JSON key `res.users` therefore generates `$..users`, which selects a different key. Keys containing punctuation and ambiguous nested objects have related representational problems. Verification uses a custom traversal rather than executing the emitted JSONPath.

**Impact:** required values are omitted or the wrong node is selected despite analysis confidence.

**Repair:** retain structured path segments and emit quoted bracket notation for literal keys. Verify with the actual JMeter/Jayway JSONPath evaluator. Filters for list selection require independent stable selector evidence.

### R15 — Fixed traversal budgets silently remove evidence

**Location:** [lineage/graph.py:61](../src/har2jmx/lineage/graph.py#L61), [entities/discovery.py:43](../src/har2jmx/entities/discovery.py#L43), [validate/extractors.py:39](../src/har2jmx/validate/extractors.py#L39), [lineage/graph.py:432](../src/har2jmx/lineage/graph.py#L432).

Lists are limited to 25 elements and nesting to depth six. Embedded discovery scans the nearest 300 prior responses. A selected `ID-0037` in item 37 of a 40-item response has no discovered producer in the fresh probe. Truncated uniqueness checks cannot establish uniqueness across an entire response.

**Impact:** realistic large captures can lose correlation, selected rows, and uncertainty evidence.

**Repair:** make traversal budgets explicit/configurable; surface truncation and downgrade affected decisions. Check uniqueness across the complete relevant response or report it unverified. An embedded substring fallback is not a substitute for full structured traversal.

### R16 — Generated UUIDs are fresh per expression, not logical request identity

**Location:** [emit/jmx.py:149](../src/har2jmx/emit/jmx.py#L149), [emit/jmx.py:196](../src/har2jmx/emit/jmx.py#L196).

A matching captured UUID is replaced by `${__UUID()}` wherever the literal occurs. When the same idempotency UUID appears in both a header and a JSON body, the plan contains two function calls. JMeter evaluates them independently. Related requests/retries can likewise lose an intentionally shared operation key.

**Impact:** matching header/body IDs diverge; idempotent retries may create separate operations.

**Repair:** initialize a named thread variable once per evidenced operation/request and reuse it at approved occurrences. Preserve retry identity and reset it at the proper lifecycle boundary.

### R17 — Some recorded JSON bodies are silently omitted

**Location:** [ir/build.py:64](../src/har2jmx/ir/build.py#L64), [emit/jmx.py:302](../src/har2jmx/emit/jmx.py#L302).

`None` represents both valid parsed JSON `null` and a failed/absent parse. The emitter requires `body.json is not None` and has no JSON raw-text fallback. Both `null` and malformed JSON text `{broken` emit no body arguments in the probe.

**Impact:** a valid `null` payload changes to an empty body; an invalid captured request is silently rewritten into another request rather than retained/reported.

**Repair:** represent parse success separately from parsed value. Preserve original text where the tool cannot safely reconstruct it and issue an actionable review/error. Include scalar/null and invalid-body cases.

### R18 — Input schema validation is incomplete

**Location:** [har/reader.py:12](../src/har2jmx/har/reader.py#L12), [ir/build.py:107](../src/har2jmx/ir/build.py#L107), [server/handler.py:150](../src/har2jmx/server/handler.py#L150).

Validation checks key presence but not container/entry types. `{"log":null}` raises `TypeError`, and `{"log":{"entries":[null]}}` raises `AttributeError`; the HTTP adapter maps these to generic 500 responses. An empty entries list is accepted by analysis and receives readiness 100/passed.

**Impact:** malformed uploads look like internal failures, and captures containing no work can look successful. The dictionary entry point also has weaker validation than byte input.

**Repair:** validate object/list types, required request fields, URLs, statuses, time values, body structures, and empty captures before analysis. Normalize expected errors to safe actionable 400 responses consistently across entry points.

### R19 — Output retention races active handlers

**Location:** [server/handler.py:59](../src/har2jmx/server/handler.py#L59), [server/handler.py:137](../src/har2jmx/server/handler.py#L137), [server/handler.py:162](../src/har2jmx/server/handler.py#L162).

Pruning enumerates and stats files while other handlers can delete them or create partial bundles. It runs before the current handler reads the JMX for its summary. Downloads separately perform existence, stat, and read operations, leaving a deletion window. Results are written directly into the shared directory before completion.

**Impact:** concurrent conversions/downloads can fail after successful generation, or an active partial result can be aged out. This is a source-level race, not a freshly observed concurrent failure.

**Repair:** publish complete bundles atomically from per-result staging directories. Synchronize retention decisions, protect active results/downloads, and open files once before streaming. Handle files that disappear during enumeration.

### R20 — UI/report data omits material review and artifact facts

**Location:** [webreport.py:174](../src/har2jmx/webreport.py#L174), [webreport.py:192](../src/har2jmx/webreport.py#L192), [webreport.py:228](../src/har2jmx/webreport.py#L228), [static/app.js:123](../src/har2jmx/static/app.js#L123).

The summary sends `parameterizationReview`, but the browser never renders it. Transaction boundary/naming confidence exists in the model but is absent from summary rows; the browser labels all controllers as user actions. Request counts describe retained capture requests rather than final explicit samplers after redirect collapsing. Dataset rows describe observed analysis rows: the fresh probe displays **one row**, while its CSV contains **three data rows**.

The browser uses a fixed 250 MB limit despite the server's configurable limit, and timed pipeline animation completes independently of backend stages. The hidden file input has no focusable picker control for ordinary keyboard use. These last points were source-inspected, not browser-tested.

**Impact:** users cannot see some necessary manual work and misunderstand generated data, pacing/actions, and progress.

**Repair:** return a final artifact manifest with actual sampler/dataset/header bindings and row counts. Render parameter review and workflow confidence; distinguish inferred controllers from evidenced user actions. Fetch effective server limits, label animation honestly, and provide a keyboard-operable file picker.

### R21 — Installed output defaults depend on a writable package ancestor

**Location:** [paths.py:17](../src/har2jmx/paths.py#L17).

The source layout's repository-root heuristic is reused for installed packages, and `mkdir()` runs at import time. In an installation under a protected Python environment, the computed ancestor may not be writable. The Render configuration explicitly overrides this path, so that deployment avoids this particular default-path issue.

**Impact:** imports/CLI startup can fail for an otherwise successful installation.

**Repair:** choose a documented user-writable application-data/temp directory at startup, with an explicit output override. Keep filesystem creation out of module imports and return clear startup errors.

### R22 — Related CSV readers do not jointly allocate a user's data

**Location:** [emit/jmx.py:684](../src/har2jmx/emit/jmx.py#L684), [entities/relationships.py:82](../src/har2jmx/entities/relationships.py#L82), [parameterize/decide.py:288](../src/har2jmx/parameterize/decide.py#L288).

Relationships and within-entity rows are discovered, and single-row datasets are consolidated. However, separate multirow datasets use independent `shareMode.all` readers with recycling. They do not express a joint per-user allocation/key join. Interleaving, unequal row counts, and different row ordering can combine a user's parent record with another user's child record.

**Impact:** account/order, patient/visit, and similar dependent data can mismatch under multiple threads even when each individual CSV row is internally aligned.

**Repair:** join related datasets by evidenced keys into atomic scenario rows, or implement an explicit keyed per-user allocator. Report intentional shared data and recycling separately. Test with multiple threads and unequal related dataset sizes.

### R23 — Pacing does not reconstruct user pauses or browser concurrency

**Location:** [emit/jmx.py:622](../src/har2jmx/emit/jmx.py#L622), [emit/jmx.py:632](../src/har2jmx/emit/jmx.py#L632), [emit/jmx.py:764](../src/har2jmx/emit/jmx.py#L764), [workflow/transactions.py:326](../src/har2jmx/workflow/transactions.py#L326).

Default think time is the median gap between business request starts, not between a completed action and the next user action. Network duration and parallel request starts are therefore mixed into the pacing estimate. The timer samples THINKTIME through twice THINKTIME, further changing the mean delay. Timestamp parsing strips offsets instead of preserving instants. Browser calls are emitted sequentially.

**Impact:** throughput and end-to-end timings can differ materially from the recorded user model. This is a modeling limitation, not necessarily a wrong choice for every API test.

**Repair:** estimate pacing from evidenced action completion/start boundaries with timezone-aware timestamps. Expose model assumptions and allow supplied pacing. Treat concurrency as explicit evidence/configuration rather than silently claiming browser-equivalent execution.

### R24 — Shared deployment serves package files and has no download ownership separation

**Location:** [server/handler.py:87](../src/har2jmx/server/handler.py#L87), [server/handler.py:162](../src/har2jmx/server/handler.py#L162), [server/handler.py:210](../src/har2jmx/server/handler.py#L210).

The inherited static handler serves `PACKAGE_DIR`, not only browser assets. Fresh localhost requests to `/engine.py` and `/server/` return **200** with source/directory listing. The same handler is used when publicly bound. Download names use a ten-hex-character result ID and have no separate user ownership/authentication check. Knowing the URL grants access to artifacts, which can contain supplied test credentials and captured data.

**Impact:** package internals are exposed, and artifact sharing is effectively bearer-link access. Source exposure alone is not proof of credential leakage; no unauthorized external access was attempted.

**Repair:** allowlist static routes and completed artifact filenames, disable directory listings, and define an explicit shared-service access/retention policy. For private/team deployment, enforce the intended ownership or stronger capability tokens. Keep this proportional to deployment: localhost personal use and public hosting have different requirements.

## Further source findings and maintenance observations

These are actionable observations beyond the main defect list; they are not counted as newly reproduced high-severity failures.

- **Non-GraphQL POST reads can still be classified as creation.** [classify/value_engine.py:395](../src/har2jmx/classify/value_engine.py#L395) treats a non-search POST/PUT/PATCH response as created-this-run. SOAP/RPC read methods can return pre-existing records. GraphQL now has operation-aware handling, but equivalent generic protocol evidence should precede transport-method heuristics. Existing P2-3 historical findings attribute unnecessary correlations to this precision problem.
- **User-scoped GET data detection is incomplete.** `_scope_tokens()` considers path/query, and `_reclassify_user_scoped()` makes one pass. A resource scoped only by bearer/cookie identity or indirectly through another reclassified resource is not reliably distinguished from a shared catalog. A HAR often cannot prove ownership from auth presence alone; report uncertainty where no independent scope contract exists.
- **HTML/XML parsing is sensitive to representation.** Hidden-input/meta regexes require particular attribute ordering and do not parse HTML entities. XML attributes are collected as response values, but extractor selection assumes element text. Verification can escalate some cases, but the pipeline should preserve structured attribute/text identity rather than collapse them. Use HTML/XML parsers where practical and retain malformed-source review paths.
- **Regex verification is not actual JMeter verification.** `_check_regex()` runs Python regex and calls a correct first match `UNIQUE` even if there are multiple matches. JMeter uses Apache ORO; the cookie helper explicitly accounts for one engine difference, but generic expressions remain a portability boundary. Define first-match correctness separately from uniqueness and validate relevant emitted expressions with JMeter.
- **GraphQL input representations need broader coverage.** Batched bodies, GET operations, unnamed/raw `application/graphql`, and arbitrary variable names do not all share the dict-based operation/variables path. The variable slot-role check expects `request.body:variables.*`, while lineage unwraps dict variables before creating slots. Review these cases with arbitrary field names and avoid implying universal GraphQL support from standard fixtures.
- **Emission mutates analysis objects.** `build_jmx_xml()` prunes `result.parameterization`, while metrics are computed earlier. The new binding identity layer is a useful separation, but a distinct emission result would make stale metrics, repeated emission, and UI consistency easier to reason about.
- **Version metadata disagrees.** `pyproject.toml` is `0.1.0`; `src/har2jmx/__init__.py` is `1.0.0`. Use one version source.
- **Lint is not currently a CI gate.** CI installs application/pytest and runs tests plus deployment smoke. Ruff/mypy are documented development commands but not checked there. Add appropriately scoped gates after establishing a consistent baseline; do not confuse the inherited Ruff findings with the repository's explicit rule policy.
- **Some assertions always pass.** `tests/test_emit.py:305` uses `assert qblock is None or True`; `tests/test_parameterization_usage_aware.py:98` also has an always-true expression. Remove or replace them with assertions that fail when request fidelity regresses.
- **The dry-run matrix excludes non-`sample_*` fixtures.** `tests/test_dryrun.py` includes all example HARs but only `sample_*.har` fixtures. The omitted auth/SPA fixtures do have targeted tests; they are simply not all subject to the generic emission gate. Include all intended supported fixtures in that gate.
- **Runtime smoke is shallow.** `scripts/smoke_deployment.py` checks startup/health/assets, not upload conversion, ZIP contents, or download availability. The installed-package path is checked by CI, while this review ran its source mode only.
- **Unsupported transports are detected without a complete emission policy.** WebSocket/gRPC detection appears in the application profile, but emitted ordinary HTTP samplers cannot reconstruct those sessions. Surface required plugins/manual work at conversion time rather than only mentioning them in documentation.
- **Upload file bytes are unavailable.** Multipart recovery preserves fields/file metadata, and emitted JMeter file paths require local runtime files. Missing binaries should be explicit in the downloadable review manifest. This is a capture/runtime input requirement, not a promise that the HAR can recreate uploaded files.
- **Large-capture performance needs measurement.** `ClassificationResult.by_value()` is linear, several stages rebuild/search related structures, and naming/content traversal has additional recursive passes. Bounded response scans help one path, but no fresh large-memory/latency profile was performed. Profile realistic large captures before adding ad hoc limits that silently weaken correctness.
- **Documentation overstates guarantees.** The UI says production-ready/any number of users; supported-patterns documentation says every extractor has a health assertion and an empty validator issue list means production-clean. R03, R06, R07, and R12 directly contradict those claims. Describe assisted generation and actual validation scope. The earlier architecture review is tied to an older commit, so its now-fixed issues should not be copied as current defects.

## Existing fixes verified or preserved in this review

The following areas have fresh passing regression coverage and should not be reported as the old defects simply because an earlier review mentioned them:

| Area | Present implementation / evidence |
|---|---|
| Authentication freshness | Accepted auth dependencies use runtime variables, producer reset/freshness checks, and stop-thread behavior; focused freshness tests pass. |
| Redirect execution | Dedicated ownership policy, current Location capture, and explicit/automatic hop decisions; redirect tests pass. |
| Static-looking business content | `content_role.py` recovers structured data contracts from some static-looking routes; content-retention tests pass. R10 concerns remaining early-exclusion cases. |
| Native multipart fields | Reader recovers fields/file metadata when params are empty; multipart tests pass. Binary reconstruction remains a limitation. |
| CSV/runtime namespace ownership | `bindings.py` reserves runtime/plan/generated names and gives conflicting CSV owners stable names; binding tests pass. R05 concerns the separate runtime identity/global substitution model. |
| Repeated input fields | Input planning now adds step-specific names for differing values instead of always taking the first same-named field. |
| Workflow cuts and labels | Captured navigation/event context refines boundaries and names; uncertainty is stored in the model. R20 concerns communicating that uncertainty. |
| CI/deployment scaffolding | A CI workflow and Render blueprint exist, and source startup smoke passes. The older review's “no CI” observation is obsolete. |

## Historical benchmark evidence, separate from fresh review results

The existing [P2-3 implementation report](../../p2-3-variable-binding-20261004/P2_3_IMPLEMENTATION_REPORT.md) reports:

- 202/202 inputs converted after the binding fix.
- 16 demonstrated CSV/runtime collisions and 21 corrupted consumers were fixed.
- 1,146 numeric JSON type mismatches remained unchanged.
- 22 independent dependencies still had failed consumers.
- 41 unused extractors remained in the unseen corpus.
- 11 of 143 JSONPath source checks remained unresolved.
- The unseen52 classification was 29 blocked, 16 requiring review, four capture-limited, and three provisionally static-ready.

The [P2-4 boundary report](../../p2-4-interaction-boundaries-20261005/TRANSACTION_BOUNDARY_ANALYSIS.md) reports 202/202 conversions and 701 emitted controllers, with 274 uncertain boundaries and 481 uncertain business semantics. It states that protected sampler properties, extraction, CSVs, authentication, and redirect behavior were unchanged in that change.

These counts are **historical corpus measurements**, not freshly remeasured totals for this review. Both reports explicitly distinguish JMeter loading/binding checks from live HTTP replay. Fresh probes independently confirm several of the underlying remaining defect classes.

## Module coverage map

| Area | Review focus and outcome |
|---|---|
| Entry points, paths, packaging | Startup/install paths, metadata, standard-library runtime, package assets; R21 and version mismatch. |
| HAR reader and normalized IR | Container validation, body typing, query/body identity, base64, multipart/file metadata, optional browser context; R01/R02/R17/R18. |
| Noise/content classification | Static/content role precedence, auth/download retention, polling, refresh recovery; R10/R11 and remaining method/path heuristics. |
| Application/auth understanding | Evidence bags, fingerprints, OAuth/SAML/cookie/transport detection; detection is useful but not runtime proof. |
| Workflow modules | Legacy timing groups, evidence refinement, names, supporting requests, uncertainty; R20/R23. |
| Entities/relationships | Record traversal, identity aggregation, first-value row merging, relationship evidence/topology; R05/R15/R22. |
| Lineage | Normalization, exact/embedded slots, producers/consumers, traversal budgets; R05/R15. |
| Value lifecycle | GraphQL operation resolution, read/runtime/creation heuristics, scope and unknown handling; further precision findings. |
| Correlation and cookies | Candidate naming, necessity/rejection/supersession, extractor expression construction, shared cookie grammar; R08/R14. |
| Parameter intent/context/planning | User/config/telemetry distinctions, approved slots, aliases, entity/input dataset consolidation; R12/R20/R22 and GraphQL slot representation. |
| JMX, bindings, auth, redirects | Request fidelity, globals, replacement typing/escaping, variable ownership, extractor placement, JMeter tree structure, CSVs and warnings; R01–R09/R12/R16/R17. |
| Replay/extractor/static validation | Analysis timing, source match checks, final feasibility, XML/variable checks; R06/R07/R14/R15. |
| Web summary and browser assets | Escaping of capture-derived strings, data/UI agreement, warnings, file picker, responsive/reduced-motion CSS; R20. No demonstrated DOM injection is claimed. |
| HTTP adapter | Upload framing/memory, errors, routing, downloads, artifact lifecycle; R13/R18/R19/R24. |
| Tests/examples | Full execution, generic dry-run inclusion, focused defect tests, assertion strength, local probes; passes plus coverage gaps documented above. |
| CI/Render/smoke/docs | Actual workflow/configuration, runtime path override, service exposure, validation claims, known limits; no deployment was changed or attempted. |

## Recommended repair order and acceptance checks

1. **Request fidelity:** R01–R04 and R17. Use a deterministic local HTTP application to inspect exact URL, content type, body bytes, parsed types, escaping, duplicate arguments, and multipart parts from actual generated JMeter execution.
2. **Runtime identity and correctness gates:** R05–R08, R14–R16. Base bindings on occurrence/producers, guard all required values, and reconcile final readiness/warnings. Include changed/failed producer responses and loop-two behavior.
3. **Traffic and data semantics:** R09–R12, R22/R23. Assert exact header applicability, required request retention, retry equivalence, supplied/constrained rows, related per-user data, and explicitly chosen pacing/concurrency.
4. **Adapter reliability:** R13/R18/R19/R21/R24. Test invalid lengths/types, empty uploads, parallel conversions, retention during downloads, large-upload budget enforcement, installed-user startup, and allowlisted routes.
5. **UI and maintenance:** R20 and the additional observations. Display final artifact facts/review items, correct guarantees, unify versions, strengthen assertions, and add consistent CI checks.

A repaired plan should pass three distinct gates: **source-fidelity checks**, **actual JMeter expression/extractor checks**, and **local HTTP replay across multiple users/iterations**. Passing XML loading or the current static validator establishes only a subset of those guarantees.

## Reproducing this review

The probe script uses only Python standard-library dependencies plus the source package. It writes evidence and synthetic outputs under `code-review-20261005`, and sends only local requests to its temporary test server.

From the repository root in PowerShell, with a working Python installation and pytest available:

```powershell
$env:PYTHONPATH = 'src'
New-Item -ItemType Directory -Force '../code-review-20261005' | Out-Null
python -m pytest --basetemp='../code-review-20261005/pytest-temp-repeat' --junitxml='../code-review-20261005/pytest-repeat.xml' -q
python scripts/smoke_deployment.py --source
python ../code-review-20261005/reproduce_findings.py
```

The fresh review used the existing uv-managed Python 3.14 interpreter and existing pytest dependencies. It did not install dependencies, change deployment settings, contact business applications, publish code, or alter production behavior.
