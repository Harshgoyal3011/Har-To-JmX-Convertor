"""Check the installed package using the same environment as a hosted service."""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", action="store_true", help="Check the source tree without installing it")
    args = parser.parse_args()
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]

    with tempfile.TemporaryDirectory() as directory:
        env = os.environ.copy()
        env.pop("PYTHONPATH", None)
        if args.source:
            env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
        env.pop("HAR2JMX_PORT", None)
        env.update({
            "HAR2JMX_HOST": "127.0.0.1",
            "PORT": str(port),
            "HAR2JMX_OUTPUT": str(Path(directory) / "generated"),
            "PYTHONUNBUFFERED": "1",
        })
        base = f"http://127.0.0.1:{port}"
        with tempfile.TemporaryFile() as log:
            process = subprocess.Popen(
                [sys.executable, "-m", "har2jmx"], cwd=directory, env=env,
                stdout=log, stderr=subprocess.STDOUT,
            )
            try:
                deadline = time.monotonic() + 30
                while True:
                    if process.poll() is not None:
                        raise RuntimeError("Installed web service exited during startup")
                    try:
                        with urllib.request.urlopen(f"{base}/healthz", timeout=2) as response:
                            if response.status != 200 or json.load(response) != {"status": "ok"}:
                                raise RuntimeError("Unexpected health-check response")
                        break
                    except (urllib.error.URLError, TimeoutError):
                        if time.monotonic() >= deadline:
                            raise RuntimeError("Hosted PORT was not reachable within 30 seconds")
                        time.sleep(0.1)

                for route, content_type in (
                    ("/", "text/html"),
                    ("/static/app.js", "javascript"),
                    ("/static/styles.css", "text/css"),
                ):
                    with urllib.request.urlopen(f"{base}{route}", timeout=5) as response:
                        if response.status != 200 or content_type not in response.headers["Content-Type"]:
                            raise RuntimeError(f"Installed web asset failed: {route}")
                        if not response.read():
                            raise RuntimeError(f"Installed web asset was empty: {route}")
                mode = "source tree" if args.source else "installed package"
                print(f"Deployment smoke check passed ({mode}): platform PORT, health check, UI, and assets.")
            except Exception:
                log.seek(0)
                sys.stderr.write(log.read().decode("utf-8", errors="replace"))
                raise
            finally:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


if __name__ == "__main__":
    main()
