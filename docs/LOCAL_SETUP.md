# Run the application locally

This guide applies to both repositories:

- [Harshgoyal3011/Har-To-JmX-Convertor](https://github.com/Harshgoyal3011/Har-To-JmX-Convertor)
- [Harsh-SDETTech/Har-To-JMX_Convertor_Perf](https://github.com/Harsh-SDETTech/Har-To-JMX_Convertor_Perf)

The application runs a local web server. Open it in your browser, upload a HAR,
and download a JMeter plan with its CSV data and any manual-review report.

## Requirements

- Git, to clone and update the repository.
- Python **3.10 or newer**, including `pip` and virtual environment support.
- A browser and a HAR capture. Include response bodies when recording the HAR.
- Internet access for cloning and the initial package installation.

Python's standard library supplies the application's runtime. Apache JMeter and
Java are needed only when you want to execute the generated test plan.
If the repository is private, use a GitHub account with repository access.

## 1. Clone either repository

For the Harsh-SDETTech repository:

```bash
git clone https://github.com/Harsh-SDETTech/Har-To-JMX_Convertor_Perf.git
cd Har-To-JMX_Convertor_Perf
```

Alternatively, for the original repository:

```bash
git clone https://github.com/Harshgoyal3011/Har-To-JmX-Convertor.git
cd Har-To-JmX-Convertor
```

Choose one option, then run the commands below from that repository folder.

## 2. Install and start

### Windows PowerShell

```powershell
python --version
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m har2jmx
```

If `python` is unavailable but the Python launcher is installed, use `py -3`
instead of `python` for the first two commands. These commands call the virtual
environment directly, so PowerShell script activation is unnecessary.

### macOS or Linux

```bash
python3 --version
python3 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/python -m har2jmx
```

On Debian/Ubuntu, if virtual environment creation reports that `ensurepip` or
`venv` is missing, install the distribution's `python3-venv` package and retry.

The editable installation (`-e .`) runs the code from your checkout and keeps
the default `generated/` output directory there.

## 3. Open and use the application

1. Keep the server terminal running and open **http://localhost:8000**.
2. Choose a `.har` file. For a first check, use `tests/fixtures/sample_flow.har`.
3. Set concurrent users, iterations, ramp-up, and optional hold/think time.
4. Submit the capture and inspect transactions, implemented correlations,
   parameters, replay findings, and manual-review items.
5. Download the ZIP bundle and extract it before opening the `.jmx` in JMeter.

The application processes the uploaded capture on the machine running the
server. Conversion does not execute requests against the captured application.
The default output directory is `generated/` in the checkout. The server retains
the latest **50** result bundles by default, so download results you want to keep.

**http://localhost:8000/healthz** should return `{"status": "ok"}`.
Stop the server with **Ctrl+C**.

## Start it again later

Open a terminal in the same repository folder. Installation is needed only once:

```powershell
# Windows PowerShell
.\.venv\Scripts\python.exe -m har2jmx
```

```bash
# macOS/Linux
.venv/bin/python -m har2jmx
```

## Use another port

For example, if port 8000 is occupied, start on 8001:

```powershell
# Windows PowerShell
$env:HAR2JMX_PORT = "8001"
.\.venv\Scripts\python.exe -m har2jmx
```

```bash
# macOS/Linux
HAR2JMX_PORT=8001 .venv/bin/python -m har2jmx
```

Open **http://localhost:8001**. `HAR2JMX_PORT` takes precedence over `PORT`;
without either setting, the application uses 8000.

## Allow another computer on your network to open it

```powershell
# Windows PowerShell
$env:HAR2JMX_HOST = "0.0.0.0"
.\.venv\Scripts\python.exe -m har2jmx
```

```bash
# macOS/Linux
HAR2JMX_HOST=0.0.0.0 .venv/bin/python -m har2jmx
```

The other computer opens `http://<server-computer-IP>:8000`, using the server
computer's LAN address. If you changed the port, use that port instead. Allow
the listening port through the firewall when required. `0.0.0.0` is a bind
address; use the LAN IP in the browser. The app has no user-login layer, so
share it only on a network where intended users can reach it.

## Configuration

Set environment variables in the server terminal before starting the app.

| Variable | Default | Purpose |
| --- | --- | --- |
| `HAR2JMX_HOST` | `127.0.0.1` | Bind locally; use `0.0.0.0` for network access. |
| `HAR2JMX_PORT` | Falls back to `PORT`, then `8000` | Listening port. |
| `HAR2JMX_OUTPUT` | Checkout's `generated/` directory | Where conversion files are written. |
| `HAR2JMX_MAX_UPLOAD_MB` | `250` | Server upload ceiling in MiB. |
| `HAR2JMX_KEEP_RESULTS` | `50` | Number of recent result bundles retained. |

The browser also checks a fixed 250 MiB file limit. Changing the server upload
limit alone does not change that browser check. The server limit includes the
multipart upload envelope as well as the file.

## Run the generated JMeter plan

Install Apache JMeter 5.x with a compatible Java version. Extract the bundle,
keep its `.jmx` and CSV files together, and open the plan using **File > Open**
in JMeter. Review `BASE_URL`, `PROTOCOL`, load settings, CSV data, upload-file
paths, and manual-review findings. Supply the actual files for multipart
uploads; the HAR records file metadata rather than a reusable local file.

Run a small validation before increasing users. The readiness score describes
static checks against the capture; a live run establishes whether fresh login,
extraction, data, and request behavior work in the target environment.

After validation, execute a non-GUI run from the extracted bundle directory:

```bash
jmeter -n -t <downloaded-plan-name>.jmx -l results.jtl
```

Replace `<downloaded-plan-name>.jmx` with the actual filename. On Windows use
`jmeter.bat` or its full path if JMeter is not on `PATH`.

## Update a local installation

Stop the server first. From a clean checkout:

```powershell
# Windows PowerShell
git pull --ff-only
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m har2jmx
```

```bash
# macOS/Linux
git pull --ff-only
.venv/bin/python -m pip install -e .
.venv/bin/python -m har2jmx
```

If Git reports local changes or diverged history, resolve those before updating.

## Troubleshooting

| Symptom | Action |
| --- | --- |
| `python`/`python3` is not found | Install Python 3.10+ and reopen the terminal; on Windows try `py -3`. |
| `No module named har2jmx` | Install with the same `.venv` interpreter used to start the app, from the repository root. |
| Address already in use / Windows error 10048 | Stop the earlier server or set `HAR2JMX_PORT=8001`. |
| Browser cannot connect | Check the server terminal, matching host/port, and `/healthz`. Keep the terminal running. |
| Invalid HAR / HTTP 400 | Export a HAR containing `log.entries`; use the sample fixture to check setup. |
| HTTP 413 / file too large | Use a smaller capture or review the server and browser limits described above. |
| Missing or incomplete correlations | Record the producing responses with bodies enabled, then review the UI and downloaded checklist. |
| CSV/file not found in JMeter | Extract the ZIP and correct CSV or upload-file paths in the plan. |

For the full processing flow, see [ARCHITECTURE.md](ARCHITECTURE.md).
For hosted setup, see [DEPLOYMENT.md](DEPLOYMENT.md). The Harsh-SDETTech
repository also includes automatic Codespaces startup; see its README.
