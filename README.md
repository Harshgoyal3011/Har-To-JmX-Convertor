# har2jmx — HAR → JMeter

Convert a browser **HAR** capture into a correlated, parameterized **Apache JMeter** test plan
(`.jmx` + CSV data). Record a real journey; har2jmx rebuilds it as a replayable load test:

- **Correlation** — extract server-generated values (session cookies, CSRF, created ids) only when
  they are required for replay. Discovery stays high-recall; a necessity gate decides what is emitted.
- **Parameterization** — lift user inputs and selected existing records into CSV datasets.

Python 3.10+, **standard library only** at runtime.

## Quick start

```bash
# from the repo root
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e .                 # installs the `har2jmx` command

har2jmx                          # local UI at http://127.0.0.1:8000
```

Open <http://127.0.0.1:8000>, upload a HAR, set threads / loops / ramp, download the zip.
Stop the server with `Ctrl+C`.

From source without installing: `PYTHONPATH=src python -m har2jmx`.

## Project layout

```
src/har2jmx/           live converter
  engine.py            analyze(har) → EngineResult
  ir/                  HAR → normalized capture
  classify/            request noise + value class
  understand/          app / auth (evidence only)
  workflow/            user-action transactions
  entities/            entities + relationships
  lineage/             producer → value → consumers
  correlate/           candidates + necessity gate
  parameterize/        intent + CSV datasets
  validate/            replay + extractor checks
  emit/                JMX + dry-run validate
  webreport.py         UI JSON (aligned with JMX extractors)
  server/ + static/    local web UI
tests/
examples/
docs/ARCHITECTURE.md
generated/             runtime output (git-ignored)
```

## Pipeline

```
HAR → analyze (12-stage IR) → emit_jmx → zip
```

Correlation path: **discover candidates → downstream dependency → necessity gate → required →
extractors in JMX**. The UI “Correlations” list is those required variables, not the candidate set.

See **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** for each module and
**[docs/SUPPORTED_PATTERNS.md](docs/SUPPORTED_PATTERNS.md)** for extractor locations and limits.

## Development

```bash
pip install -e ".[dev]"
pytest
ruff check src
mypy
```

## Automatic deployment

The included [Render Blueprint](render.yaml) deploys pushes to `main` after
GitHub Actions tests and a web-service smoke check pass. Connect the repository
to Render once using the [deployment guide](docs/DEPLOYMENT.md).

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/Harshgoyal3011/Har-To-JmX-Convertor)
