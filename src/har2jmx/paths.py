from __future__ import annotations

import os
from pathlib import Path

# Directory of the installed package (…/src/har2jmx). Static web assets ship
# inside the package so the server works whether run from source or pip-installed.
PACKAGE_DIR = Path(__file__).resolve().parent
STATIC_DIR = PACKAGE_DIR / "static"

# Served root for the stdlib HTTP handler; "/static/…" resolves under here.
ROOT = PACKAGE_DIR

# Runtime output (JMX, CSV, reports, zip). Lives outside the package: honour an
# explicit override, else default to "generated/" beside the repo when running
# from source. The CLI will make this an explicit per-invocation argument.
_REPO_ROOT = PACKAGE_DIR.parent.parent
OUTPUT_DIR = Path(os.environ.get("HAR2JMX_OUTPUT") or (_REPO_ROOT / "generated"))
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
