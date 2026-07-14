# Self-Healing HAR → JMeter

Convert a browser HAR capture into a correlated, parameterized JMeter test plan.

## Stack

- Python 3.10+ (stdlib only — no third-party packages)
- Stdlib HTTP server (`ThreadingHTTPServer`)
- Vanilla HTML / CSS / JS frontend

## Setup & run

From the project folder:

```bash
cd "/Users/mrmed/Desktop/python project"

# Create a virtual environment (skip if .venv already exists)
python3 -m venv .venv

# Activate it
source .venv/bin/activate

# Install dependencies (stdlib-only; this step is safe and keeps the workflow consistent)
pip install -r requirements.txt

# Start the app
python -m app
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000), upload a HAR, set workload options, and download the generated zip (JMX + CSV + reports).

Stop the server with `Ctrl+C`.

### Already have `.venv`?

```bash
cd "/Users/mrmed/Desktop/python project"
source .venv/bin/activate
pip install -r requirements.txt
python -m app
```

## Package layout

| Path | Role |
|------|------|
| `app/har/` | HAR parse, filter, transaction grouping |
| `app/parameters/` | Business-input discovery and CSV entities |
| `app/correlations/` | Dynamic-value correlation engine |
| `app/validation/` | Rules 8–10 quality gate |
| `app/jmx/` | JMX XML builder |
| `app/reports/` | Summary JSON and markdown reports |
| `app/pipeline.py` | End-to-end `convert_har` |
| `app/server/` | HTTP API and static file serving |
| `static/` | Upload UI |
| `generated/` | Runtime output |
