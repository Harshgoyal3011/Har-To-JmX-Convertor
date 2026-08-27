# har2jmx — Self-Healing HAR → JMeter

Convert a browser **HAR** capture into a correlated, parameterized **Apache JMeter** test plan
(`.jmx` + CSV data + reports). Record a real business journey in the browser; `har2jmx`
reconstructs it as a replayable load test — automatically handling the two hard parts of
JMeter scripting:

- **Correlation** — captures server-generated dynamic values (session cookies, CSRF tokens,
  object IDs) and replays them, *only* when it can prove the value is reused downstream.
- **Parameterization** — lifts user inputs (emails, search terms, chosen IDs) into CSV data
  so each virtual user varies, and clusters related fields into coherent records.

Python 3.10+, **standard library only** — no third-party runtime dependencies.

## Quick start

```bash
# from the repo root
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e .                 # installs the `har2jmx` package + command

har2jmx                          # starts the local web UI at http://127.0.0.1:8000
```

Open <http://127.0.0.1:8000>, upload a HAR, set the workload (threads / loops / ramp), and
download the generated zip. Stop the server with `Ctrl+C`.

> Running from source without installing? Use `PYTHONPATH=src python -m har2jmx`.

## Project layout

```
har2jmx/
├── src/har2jmx/         ← the package (importable, installable)
│   ├── pipeline_v2.py       end-to-end conversion: convert_har_v2()
│   ├── models.py            core dataclasses (SamplerModel, CorrelationRule, …)
│   ├── patterns.py          the regex/rule knowledge base
│   ├── har/                 parse HAR, filter static noise, group transactions
│   ├── analyzer/            structure, dependency graph, value-origin, review
│   ├── correlations/        find & classify server-generated dynamic values
│   ├── parameters/          discover business inputs, cluster entities, write CSVs
│   ├── validation/          Rules 8–10 quality gate + auto-corrections
│   ├── jmx/                 assemble the JMeter XML test plan
│   ├── reports/             markdown reports + JSON summary
│   ├── server/              stdlib HTTP API + static/ web UI
│   └── ir/                  intermediate representation (migration in progress)
├── tests/               ← test suite (+ fixtures/)
├── examples/            ← sample HAR captures
├── docs/                ← ARCHITECTURE.md and archived design notes
├── generated/           ← runtime output (git-ignored)
└── pyproject.toml
```

## The pipeline

One call, six stages (`src/har2jmx/pipeline_v2.py`):

```
HAR bytes → analyze → correlate → parameterize → validate → review → emit → zip
```

See **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** for the full design, the stage
contracts, and the roadmap to a market-ready CLI.

## Development

```bash
pip install -e ".[dev]"
pytest            # run the tests
ruff check src    # lint
mypy              # type-check
```
