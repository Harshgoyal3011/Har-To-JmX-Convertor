# Architecture

This is the source-of-truth design for `har2jmx`. It describes the target the codebase is
being shaped toward — chosen so the same core can ship as a CLI today and a hosted service
later without a rewrite. Legacy design notes live in [`archive/`](archive/).

## Guiding principle: a pure core, with thin adapters

```
                 ┌─────────────────────────────────────────────┐
   HAR bytes ───▶│                CORE ENGINE                  │───▶ BuildResult
   + config      │   pure functions · no HTTP · no filesystem  │     (+ .jmx, CSVs, reports)
                 │   convert(har_bytes, config) -> BuildResult │
                 └─────────────────────────────────────────────┘
                        ▲                 ▲                 ▲
                        │                 │                 │
                 ┌──────┴──────┐   ┌──────┴──────┐   ┌──────┴───────┐
                 │  CLI (Phase │   │  Web server │   │  SaaS backend│
                 │  3)         │   │  (server/)  │   │  (future)    │
                 └─────────────┘   └─────────────┘   └──────────────┘
```

The engine knows nothing about how it was invoked. Every surface — the CLI in someone's
CI pipeline, the local web UI, a future hosted product — is a **thin adapter** that calls one
stable function and formats the result. Improve the engine and every adapter benefits; change
an adapter and the engine is untouched. This separation is what keeps the product cheap to
evolve, and the codebase is already ~80% of the way there.

## The one contract

```python
def convert(har_bytes: bytes, config: dict) -> BuildResult: ...
```

Everything flows through this. `BuildResult` (`models.py`) is the complete, serializable
output: samplers, parameters, correlations, entities, output paths, quality-gate score and
auto-corrections. Reports and the JSON summary are *projections* of `BuildResult` — they never
recompute anything.

## Six stages as explicit seams

The pipeline is a fixed sequence of stages, each with a clear input → output contract. New
capabilities slot into a seam without touching the orchestrator.

| # | Stage | Input → Output | Home | Extends to… |
|---|-------|----------------|------|-------------|
| 1 | **analyze** | HAR bytes → samplers + transactions + value index | `har/`, `analyzer/engine.py` | new protocols (GraphQL, gRPC-web), new transaction rules |
| 2 | **correlate** | samplers → proven correlation rules + dependency graph | `correlations/`, `analyzer/dependency_graph.py` | path-value correlation, boundary extractors |
| 3 | **parameterize** | samplers → parameters → CSV entities | `parameters/` | smarter entity clustering, data generators |
| 4 | **validate** | everything → quality gate (score + corrections) | `validation/` | new rules, configurable thresholds |
| 5 | **review** | everything → findings + recommendations | `analyzer/review.py` | genuine ML scoring (today: heuristics) |
| 6 | **emit** | model → `.jmx` (+ reports) | `jmx/`, `reports/` | alternate outputs (Gatling, k6, JUnit) |

**Design rule:** a stage depends only on the models produced by earlier stages, never on an
adapter or on global state. Keep the seams clean and stages 2–6 stay independently testable
and replaceable.

## The vocabulary (`models.py`)

Five dataclasses are the shared language every stage speaks:

- **`SamplerModel`** — one HTTP exchange; the working unit through the whole pipeline.
- **`CorrelationRule`** — a proven dynamic value: producer, extractor, confidence, consumers.
- **`Parameter`** — a business input lifted to a variable; may be CSV-bound.
- **`DataEntity`** — a cluster of parameters that form one record → one CSV file.
- **`BuildResult`** — the full conversion output; what adapters and reports read.

## Physical layout

`src/` layout with a real package name (`har2jmx`) — the modern packaging standard: it prevents
import-shadowing, makes `pip install` unambiguous, and separates shippable code from repo
scaffolding. Runtime output (`generated/`) lives **outside** the package; static web assets ship
**inside** it (`har2jmx/static/`) so the server works when pip-installed.

See the tree in the [README](../README.md#project-layout).

## Known debt (being paid down, in order)

These are consolidation tasks, not redesigns — the domain logic is sound. Full detail in the
Phase-1 context map.

1. **Two pipelines** — `pipeline.py` (dead) vs `pipeline_v2.py` (live). Collapse to one
   `pipeline.py` exposing `convert()`.
2. **Engine twins** — `discover.py` + `discover_enhanced.py` in both `correlations/` and
   `parameters/`. Merge each pair into one module (the enhanced logic is the keeper; it reuses
   the base's helpers).
3. **IR half-migration** — `HAR → ScriptIR → samplers` flattens immediately. Either finish the
   migration deliberately or drop the IR; don't carry a half-built one.
4. **Redundant scan** — `value_origin.py` re-walks every request/response that `correlate`
   already scanned; fold it into the single scan.
5. **Honest naming** — `AIReviewLayer` contains no model; rename to `HeuristicReviewer`.

## Roadmap to market-ready

Ordered so the base is clean before features land (audience: performance/QA engineers).

- **Phase 0 — Structure** ✅ *(done)* — `src/` layout, package rename, docs/tests homes,
  `pyproject.toml`, git checkpoint.
- **Phase 1 — Consolidate** — pay down the debt above; one pipeline, one engine per concern.
- **Phase 2 — Test harness** — real pytest suite + a **golden-file JMX test** (locks behaviour
  so refactors can't silently drift), ruff + mypy, CI.
- **Phase 3 — CLI** — `har2jmx convert capture.har -o out/` with a `--min-score` gate for CI;
  `har2jmx serve` for the UI. One entry point over the same `convert()`.
- **Phase 4 — Features** — path-value correlation, boundary extractors, multipart/GraphQL,
  capture allow/deny controls, a self-contained HTML report, PyPI + Docker publishing.
