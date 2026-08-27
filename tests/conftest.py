"""Make the `src/` package importable during tests.

`pyproject.toml` already sets `pythonpath = ["src"]` for pytest; this belt-and-
braces insert also lets the legacy scripts in this folder be run directly
(`python tests/test_*.py`) until they are migrated to proper pytest cases.
"""
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
if SRC.is_dir() and str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
