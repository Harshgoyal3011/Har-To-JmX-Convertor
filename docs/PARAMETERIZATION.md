# Parameterization necessity

Parameterization asks whether a tester would intentionally supply or vary a value.
Client origin is evidence, not sufficient intent. Dynamic, numeric, unique or
long values do not automatically become CSV columns.

The change is confined to parameter intent/planning and CSV substitution. It does
not alter value classification, lineage, correlation discovery or necessity,
extractor verification, transactions, request exclusions, or assertion logic.

## Decision path

1. Preserve runtime ownership: runtime classifications never enter CSV. Unknown
   runtime values remain review items, not fallback test data.
2. Examine concrete request occurrences and their payload ancestors. Browser
   PerformanceEntry/timing structures and diagnostic subtrees are observations.
   Unfamiliar fields within those structures inherit that role.
3. Distinguish protocol negotiation, pagination, sorting and configuration from
   credentials, challenge answers, search terms and business arguments.
4. Require client provenance plus input context, or existing-record identity and
   consumption evidence. Equal response labels and fixed route literals are not
   sufficient evidence of record selection.
5. Leave uncertain intent in REVIEW. Every emitted column retains a reason and
   approved slots.

EXCLUDE means excluded from test data. This layer does not remove telemetry
requests from replay or change the existing noise classifier.

## Logical identity and substitution

Normalized field spellings sharing a lineage value can use one logical column.
Explicit login-identity aliases can share a column when they carry the same value;
passwords and unrelated fields with equal samples remain separate. Different
values in the same named field at different steps retain separate columns.

CSV substitutions use approved request indices and structured locations. They do
not inherit the global literal substitution used by correlation. Encoded HAR form
spellings bind to decoded CSV values, with JMeter encoding enabled on form/query
arguments. This avoids separate encoded/decoded columns and prevents a parameter
from rewriting an equal-valued pagination or unrelated field.

## Validation on the audited capture

The private Systech capture contains 134 requests. Before implementation, all 621
classified values were audited for source, decision and intended action. The
private HAR, candidate values and generated test data are kept outside this repo.

| Metric | Before | After |
|---|---:|---:|
| Emitted CSV columns | 58 | 2 |
| Username/login identity column | Missing | `signInName` |
| Password column | Missing from emitted plan | `password` |
| CSV bytes at 100 rows | 68,508 | 4,110 |
| Unnecessary columns against the audit | 58 | 0 |
| Missed expected inputs | 2 | 0 |
| Telemetry/configuration/runtime columns | Present | 0 |

Precision and recall against this capture's manually reviewed expected input set
are both 100%. This is evidence for that capture, not a universal accuracy claim.

The 74-capture corpus comparison checks complete correlation candidates/audits,
decisions, extractor checks and emitted extractor XML, classifications,
transactions and request roles against a frozen baseline. Those checks are
unchanged, and no runtime-classified value enters CSV. Two external captures
retain their existing dry-run warnings; these parameterization changes do not
resolve or suppress them.

Regression cases cover credentials, MFA, issued tokens and IDs, selection versus
creation, business arguments, unknown fields, telemetry structures, configuration,
equal-valued unrelated fields, repeated-step inputs, and encoded login aliases.
HAR inference remains conservative for opaque fields without input evidence.
Static validation does not establish successful live JMeter replay.
