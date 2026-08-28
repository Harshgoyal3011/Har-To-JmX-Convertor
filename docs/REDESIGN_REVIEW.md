# Redesign Review — senior engineer sign-off

Review of the 14-commit redesign (`redesign/m1-normalized-ir`): the M1–M12 reasoning pipeline plus the
JMX emitter, validated against a **real** capture.

## Architecture — assessment

**Sound.** The design is a pure staged pipeline over a single IR: `IR → noise → understanding →
workflow → entities → relationships → lineage → value classification → correlation →
parameterization → replay validation → emit`. Each stage is a pure function that annotates the IR or
returns a value object; there is no shared mutable global, and the live legacy path was never touched
(strangler migration). `engine.analyze(har) → EngineResult` is the single, testable, I/O-free entry
point every adapter calls. **84 tests, zero regressions across every milestone.**

**What's strong**
- Correlation matches whole structured slots, not substrings (M7) — the root cause of the old
  "+321 bogus consumers" is gone by construction, and a substring-decoy test guards it.
- Decisions are driven by **lifecycle classification** (M8), not ID-shape or repetition, exactly per
  the brief. Correlations and parameters are a strict partition; `UNKNOWN` is never auto-wired.
- Everything is evidence-gated and app-agnostic (no domain keyword tables); vendor patterns for
  telemetry/frameworks are the only lists, and those generalize across apps.

## Real-HAR validation (restful-booker demo API)

Captured a genuine flow (auth → search → create booking → read-back → update → delete) into
`examples/restful_booker.har` and ran the engine end to end:

| Aspect | Result |
|---|---|
| Transactions | `Login · View Booking · Create Booking · Update Booking · Delete Booking` |
| Correlations | **`token`** (`$..token`, produced at login, consumed as cookie on PUT/DELETE) and **`bookingid`** (`$..bookingid`, created by POST, consumed in later paths) — exactly the two runtime values |
| Parameters | `Auth(username,password)`, `Booking(firstname,lastname,totalprice,additionalneeds)`, `Bookingdate(checkin,checkout)` — every user input |
| False correlations | **0** |
| Replay | passed, score 97 |
| Emitted JMX | 5 Transaction Controllers, 6 samplers, 2 JSON extractors, 3 CSV Data Sets, Cookie Manager, `${THREADS}/${LOOPS}/${RAMP}` — runs for N users |

## Defect found & fixed during review

Running on the real HAR surfaced one genuine bug the synthetic fixtures had not: **user inputs echoed
back by a create response were wrongly correlated** (`firstname`, `checkin`). Root cause — lifecycle
keyed off "has a producer" instead of the *earliest occurrence overall*. Fixed so a value the client
sends before (or at) the response that echoes it is **client-originated master data**, never a runtime
correlation. Locked with `sample_echo.har` + a regression test. This is precisely the
"business data must not be correlated" rule from the brief, and it now holds on real traffic.

## Remaining nits (non-blocking)

- **Redundant computation:** `discover_relationships` is computed in a couple of stages independently;
  threading one model through `analyze` would save recomputation. Correctness unaffected.
- **Numeric params in JSON bodies** are substituted as `"${var}"` (quoted). Fine for most APIs; a
  strict-typed API may want unquoted numeric substitution — a small emitter enhancement.
- **Data variation:** single-observed-record datasets yield one CSV row (flagged LOW by the validator);
  optional synthetic row generation would improve iteration variety.

## Verdict

**Approved.** The engine does what an experienced performance engineer does — understands the flow,
correlates only what must be correlated, parameterizes the rest, and emits a clean, runnable,
N-user plan — and it now proves it on real traffic. Ship the cutover (route server/CLI through
`analyze`+`emit`, add the golden-file test, retire the legacy engine).
