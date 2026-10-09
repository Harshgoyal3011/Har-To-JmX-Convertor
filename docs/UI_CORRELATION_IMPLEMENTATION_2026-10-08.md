# UI correlation versus generated script

The reported behavior was reproduced in the latest generated plan, `har2jmx_55b54c01ad.jmx`, using the available `STD_flow_HAR_7Oct.har` capture. `SAMLRequest` and `SAMLResponse` each had an accepted correlation and generated regex extractor, but their consumer form arguments still contained captured literals. Both were nevertheless listed as completed correlations in the UI.

## Root causes and repair

HAR form params retained percent escapes in these Base64 values. Discovery normalized the values with `unquote`, while emission required the exact recorded spelling. The existing encoded-authentication alias path did not cover these accepted SAML decisions.

Emission now supplies a small, request-scoped binding for a percent-encoded form spelling only when an existing accepted correlation names that downstream request, its producer precedes the consumer, extraction is verified and the canonical substitution already belongs to that variable. HTTPArgument uses the canonical `${variable}` and performs normal runtime form encoding. No encoded aliases are added to the global literal inventory. Ambiguous owners are left unchanged. Query, raw-body and multipart construction retain their prior behavior.

The UI previously checked only whether an extractor name appeared in the JMX. It now inspects the final JMX for the enabled extractor on the producing sampler and variable references in every approved downstream request. Sampler labels, assertion strings and processor code do not count as consumer substitutions. CookieManager remains its own implementation mechanism. Missing or partial bindings are excluded from the implemented count and included in manual review, both in the UI and downloaded report. This is a reporting check, not a claim that live extraction always succeeds.

## Validation

- 525 pytest tests pass, including 11 new final-JMX/API implementation tests.
- 202 existing corpus captures convert successfully with unchanged parameterization owners and correlation decisions.
- The reported capture now has eight implemented correlations, including `${SAMLRequest}` and `${SAMLResponse}` in their intended POST form arguments.
- Actual Apache JMeter 5.6.3 replay uses the repaired plan's regex extractors and HTTP arguments against a local receiver. Producers issue fresh values containing `+`, `/` and `=`. Consumers receive those fresh values after exactly one form encoding; the independent URL query remains `tenant=acme`.
- Missing extractor, disabled extractor, wrong producer, no request reference, assertion-only reference, partial consumer coverage and unrelated encoded occurrences have focused regression coverage.
- The conversion API test downloads the resulting JMX and compares its form bindings with the returned UI implementation audit.

Evidence and the corrected plan are in `../../ui-correlation-20261008` relative to this document: `CORPUS_AUDIT.json`, `REPORTED_CAPTURE_AUDIT.json`, `WIRE_REPLAY_VALIDATION.json`, `full-pytest.xml` and `repaired/STD_flow_repaired.jmx`. `validate.py` reproduces the corpus comparison and fresh runtime wire check.

## Remaining limits

Correlation discovery, lifecycle policy, CSV ownership and occurrence foundation are unchanged. This repair does not resolve global equal-literal ownership (R05), JSON numeric typing/escaping (R03/R04), invalid JSONPath or general extraction readiness. Other correlations whose final binding is incomplete are reported for review instead of being silently counted as implemented. Regenerate a conversion to receive repaired output; existing downloaded files retain their original contents.
