# Request URL/query/body fidelity

## Analysis before implementation

The frozen parent source is captured in `../request-fidelity-20261007/parent-engine/src` with SHA-256 hashes in `VALIDATION_INPUT_MANIFEST.json`. This includes the inspection-only P2-4A occurrence foundation.

`ir/build.py` separates the URL into `HttpRequest.path` and ordered decoded `HttpRequest.query` pairs using `parse_qsl(..., keep_blank_values=True)`. `HttpRequest.url` retains the original URL spelling. The body is independently classified as JSON, GraphQL, XML, SOAP, text, form or multipart. Reader and IR changes are unnecessary.

Both defects originate in `_add_http_sampler` in `emit/jmx.py`:

- R01: the raw-body branch emits one unnamed argument and bypasses query handling. `HTTPSampler.path` contains only the base path, so queries disappear. JSON, GraphQL, XML, SOAP and text share this branch, including PUT/PATCH.
- R02: the alternate branch concatenates query pairs with form/multipart fields into `HTTPsampler.Arguments`. JMeter interprets GET/HEAD arguments as URL parameters, but POST arguments as body fields, moving recorded URL data into the body.
- Explicit redirects already use the runtime Location URL as the path and intentionally omit the captured target query. That ownership must remain unchanged.

The repair builds the sampler path from the existing substituted base path and IR query independently of body selection. Arguments contain only body data. Static query tokens retain original URL spelling only when decoded ordered pairs exactly agree with the authoritative IR query. Otherwise encoding is reconstructed from IR pairs. Approved query substitutions use existing slot lookup and JMeter `__urlencode`, replacing encoding previously supplied by HTTPArgument. Sampler labels retain their previous base-path spelling.

Validation examines final JMX and executes generated JMeter samplers against a loopback receiver. Static query spelling, repeated pairs, empty values and dynamic encoding must survive on the wire. Multipart boundaries remain JMeter-owned; validation compares received part values and file bytes.

## Scope limits

R03 numeric JSON substitution, R04 runtime JSON escaping, R05 correlation identity, lifecycle decisions, JSONPath validity, extraction readiness and transaction naming remain outside scope. Existing JSON serialization may change captured whitespace; wire probes use matching serialization to measure byte equality without changing that policy.

## Results

The only production source changed relative to the frozen P2-4A parent is `src/har2jmx/emit/jmx.py`. Its new URL helper preserves IR pair order, repetitions, blank values, encoded names and original token spelling. Approved dynamic query values use `${__urlencode(${variable})}` so reserved characters are encoded after resolution. Body construction and substitution are unchanged. Four existing test modules were adjusted to inspect query bindings in the URL; 21 focused final-JMX cases were added.

| Measurement | Before | After |
| --- | ---: | ---: |
| Unseen / frozen / existing conversions | 52 / 76 / 74 | 52 / 76 / 74 |
| Generated samplers | 2,129 | 2,129 |
| Transaction controllers | 701 | 701 |
| Recorded query samplers | 552 | 552 |
| Raw-body samplers losing query (R01) | 14 | 0 |
| Query placed in body arguments (R02) | 25 | 0 |
| Accepted correlations | 1,070 | 1,070 |
| CSV columns | 1,238 | 1,238 |
| Materialized extractors | 511 | 511 |
| Existing static dead extractors | 41 | 41 |
| Undefined request variables | 0 | 0 |
| CSV/runtime or duplicate CSV names | 0 | 0 |
| Wire probes passing query/body/content type | 2 / 21 | 21 / 21 |

All 514 pytest tests passed, including P2-4A identity tests and authentication, redirect, multipart and CSV ownership regressions. All 202 input files were checked against their frozen hashes. Exact before/after engine outputs confirm unchanged lifecycle, correlation candidates/decisions, parameterization before and after emission, request classification, transactions, authentication, redirects, bodies, lineage and extractor checks. Every generated CSV is byte-identical. Outside sampler URL and HTTP arguments, the complete final JMX structure is unchanged after ignoring XML formatting and the generated plan timestamp.

552 samplers in 135 plans changed representation: query data is now explicit in `HTTPSampler.path`, including GET queries that previously used HTTP arguments. Existing correct GET behavior is preserved on the wire. The 25 body-argument crossings comprise 17 form requests, 4 multipart requests and 4 bodyless POSTs.

## Wire evidence and practical limits

`wire_replay.py` runs actual generated samplers with Apache JMeter 5.6.3 against a Python HTTP receiver on `127.0.0.1`. The receiver records request URL, raw query, Content-Type, base64 body bytes, form pairs and multipart field/file data. The same probes run against the exact frozen emitter and the repaired emitter. JSON, GraphQL, XML, SOAP, text, form, multipart, GET, HEAD, POST, PUT, PATCH, repeated/empty/encoded query values, independent parameter slots, equal query/body literals and fresh runtime variables are covered.

All static probe queries are compared as exact raw strings, including percent-escape spelling; dynamic queries are compared against their expected freshly encoded variable values. Non-multipart bodies are compared as exact UTF-8 bytes. Multipart part values and file bytes are exact; JMeter regenerates its framing boundary, so whole multipart envelope bytes are not asserted equal to a recorder envelope. Content-Type is checked, allowing JMeter's existing empty-POST form default and generated multipart boundary. No external application traffic was replayed: the 202 real plans were audited statically, while representation semantics were executed locally.

No improvement in correlation precision or recall is claimed. Existing global literal-based binding (R05), numeric substitution/escaping (R03/R04), lifecycle false runtime assignments, invalid JSONPath, failed runtime consumers and extractor health/readiness still require separate work. The 41 static dead extractors remain. This repair restores URL/body ownership without changing those policies or silently solving their defects.

## Evidence and reproduction

The complete deliverables are in `../../request-fidelity-20261007` relative to this document:

- `QUERY_BODY_BEFORE_AFTER.csv`: all 552 changed samplers, original query, before/after URL and arguments.
- `QUERY_PRESERVATION_AUDIT.json`: ordered query ownership and dynamic binding checks.
- `WIRE_REPLAY_VALIDATION.json`: all 21 received wire records and expected comparisons.
- `FINAL_JMX_REQUEST_FIDELITY.json`: 2,129 final sampler audits.
- `REQUEST_FIDELITY_REGRESSION.json`: per-workflow decisions, CSV hashes and structural comparisons.
- `SOURCE_HASH_REPORT.json`, `VALIDATION_INPUT_MANIFEST.json`, `SOURCE_CHANGE_REPORT.md`, `full-pytest.xml`: frozen source/input hashes and test evidence.
- `before/`, `after/`, `wire-before/`, `wire-after/`: generated plans, CSVs, decisions, JMeter logs and results.

From the repository, set `PYTHONPATH=src;../parameter-test-deps` and use the installed Python interpreter. Run `../request-fidelity-20261007/run_engine.py before`, then `after`; run `wire_replay.py before`, then `after`; run `compare.py`. Run pytest with a workspace `TEMP`/`TMP` and `--basetemp` to avoid restricted system temporary directories. `prepare.py` is intentionally single-use to protect the frozen baseline.
