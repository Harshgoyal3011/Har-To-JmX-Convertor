# Missed qualified username binding

The later login form in `STD_flow_HAR_7Oct.har` submits `pf.username`. The earlier form submits `username`. Both represent the captured login identity, but only the earlier occurrence was included in the `username` CSV column and substituted in the final JMX.

The existing credential lookup removed punctuation from the whole field name, turning `pf.username` into `pfusername`, which was not an identity credential. The existing credential intent branch consequently kept only the unqualified username occurrence. This was missing input ownership evidence, rather than a server-produced correlation.

Credential lookup now applies the existing exact credential names to the explicit leaf of a dotted name. The namespace stays in the actual request field name. Existing intent, alias consolidation and slot-scoped emission then carry both approved occurrences into the same `username` CSV owner:

```text
request 16: username    = ${username}
request 25: pf.username = ${username}
```

No new CSV column is required for the reported capture. Different captured identities keep separate existing owners. Arbitrary suffixes such as `notusername` are not recognized as credentials. Credential values remain CSV inputs; correlation and lifecycle decisions are unchanged.

Validation evidence is under `../../username-binding-20261008` relative to this document: full pytest XML, corpus comparison, `USERNAME_BINDING_AUDIT.json`, `WIRE_CSV_VALIDATION.json` and `repaired/STD_username_repaired.jmx`. Tests inspect exact owned slots, final form names, variable references, encoding and CSV contents. Wire validation supplies a changed CSV username and executes the repaired HTTP arguments with Apache JMeter, checking that both forms receive that changed value and their URL queries remain independent.

This change does not address occurrence ownership throughout the full engine, JSON numeric typing/escaping or extraction readiness.

Completed validation: 533 pytest tests passed; 202 corpus conversions were unchanged, including parameterization and HTTP arguments. The additional reported capture now binds both username occurrences to its existing column. Apache JMeter 5.6.3 sent `changed+csv.user@example.test` from the test CSV as both `username` and `pf.username`, correctly escaping `+` and `@` once. The restarted live application's conversion API and downloaded JMX were checked for both bindings.
