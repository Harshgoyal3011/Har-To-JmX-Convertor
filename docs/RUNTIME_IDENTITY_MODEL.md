# Runtime occurrence identity

**Proposed design only. The experiment was rejected and production source restored.** See P2_4_VALUE_IDENTITY_ANALYSIS.md for the scope conflict and remaining defects.

Normalized literals are lookup evidence. They are never runtime owners.

An occurrence ID deterministically encodes the capture-local event index, request/response side, origin, exact transport/structured location, pair/list indices, original scalar type, and representation. A runtime owner is an exact response occurrence with its unchanged lifecycle verdict. An approved edge names that owner and an exact later request occurrence. Distinct event indices preserve retry/refresh identity. Distinct arrays and JSON types cannot share an occurrence ID.

Equality groups are retained for existing discovery and diagnostics. Separate producer occurrences within a group are not automatically aliases. A response echo can alias an upstream owner only when its issuing request already consumes that owner. Encoded and decoded forms require a known transport transformation and matching provenance. Credential transport uses the existing authentication representation policy.

Ambiguous provenance produces a review rejection. No hostname dictionary, application vocabulary, entropy threshold or artificial confidence is introduced. Distinct runtime names are needed only for distinct approved producer owners. Existing unambiguous names and P2-3 CSV naming remain stable.

The proposed final emitter resolves by request occurrence. A whole-value map is permitted only as a scoped implementation view after an exact edge has selected the owner; it must not choose an owner itself. Final JMX audits must inspect the producer extractor, variable, exact consumer expression and captured resolved value together. The rejected experiment showed that scoped maps alone are insufficient when upstream lifecycle and input-column identity has already collapsed.
