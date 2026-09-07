from __future__ import annotations

import functools
import json
import re
import traceback
import uuid
import zipfile
from html import escape
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from har2jmx.emit import emit_jmx
from har2jmx.engine import analyze
from har2jmx.paths import OUTPUT_DIR, ROOT
from har2jmx.server.multipart import parse_multipart
from har2jmx.webreport import build_web_summary


# Sane upper bounds so an absurd value can't be baked into the plan (e.g. threads=999999 would make
# JMeter try to spawn a million threads and fall over). Generous, not restrictive.
_MAX_THREADS = 2000
_MAX_LOOPS = 100_000
_MAX_SECONDS = 86_400        # 24h — ramp / hold ceiling
_MAX_THINKTIME_MS = 300_000  # 5 min per step


def _clamp(raw: str, minimum: int, maximum: int, default: int) -> str:
    try:
        return str(min(maximum, max(minimum, int(str(raw).strip()))))
    except (TypeError, ValueError):
        return str(default)


def _max_upload_bytes() -> int:
    """Upload ceiling (bytes). A HAR is JSON text; 25 MB covers very large captures while stopping a
    hostile/accidental multi-GB body from being read into memory. Raise via HAR2JMX_MAX_UPLOAD_MB."""
    import os
    try:
        mb = int(os.environ.get("HAR2JMX_MAX_UPLOAD_MB", "25"))
    except (TypeError, ValueError):
        mb = 25
    return max(1, mb) * 1024 * 1024


_RESULT_ID_RE = re.compile(r"^har2jmx_([0-9a-f]{10})")


def _keep_results() -> int:
    """How many past result bundles to retain in the output dir (HAR2JMX_KEEP_RESULTS, default 50)."""
    import os
    try:
        return max(1, int(os.environ.get("HAR2JMX_KEEP_RESULTS", "50")))
    except (TypeError, ValueError):
        return 50


def _prune_output(out_dir: Path, keep: int) -> None:
    """Retain only the newest ``keep`` result bundles; delete older ones so the output dir doesn't grow
    without bound. A single conversion writes several files sharing a ``har2jmx_<id>`` prefix, so files
    are grouped by that id and whole bundles are aged out together. ``.gitkeep`` and any file that isn't
    a har2jmx result are left untouched."""
    groups: dict[str, list[Path]] = {}
    for p in out_dir.iterdir():
        if not p.is_file():
            continue
        m = _RESULT_ID_RE.match(p.name)
        if m:
            groups.setdefault(m.group(1), []).append(p)
    if len(groups) <= keep:
        return
    ordered = sorted(groups.values(), key=lambda fs: max(f.stat().st_mtime for f in fs), reverse=True)
    for files in ordered[keep:]:                        # everything past the newest `keep` bundles
        for f in files:
            try:
                f.unlink()
            except OSError:
                pass


class AppHandler(SimpleHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/":
            self.path = "/static/index.html"
        if self.path.startswith("/download/"):
            self.serve_download(self.path.split("/download/", 1)[1])
            return
        super().do_GET()

    def do_POST(self) -> None:
        if self.path != "/api/convert":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except (TypeError, ValueError):
            length = 0
        # reject oversized uploads BEFORE reading the body into memory (avoids a memory-exhaustion DoS)
        limit = _max_upload_bytes()
        if length > limit:
            self.respond_json(
                {"error": f"Upload too large ({length // (1024 * 1024)} MB). The limit is "
                          f"{limit // (1024 * 1024)} MB — export a smaller HAR, or raise "
                          "HAR2JMX_MAX_UPLOAD_MB."},
                status=HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
            return
        try:
            upload, fields = parse_multipart(self.headers, self.rfile.read(length))
            config = {
                "threads": _clamp(fields.get("threads", "10"), 1, _MAX_THREADS, 10),
                "loops": _clamp(fields.get("loops", "1"), 1, _MAX_LOOPS, 1),
                "ramp": _clamp(fields.get("ramp", "5"), 0, _MAX_SECONDS, 5),
                "hold": _clamp(fields.get("hold", "0"), 0, _MAX_SECONDS, 0),
            }
            # think time: only set when supplied; blank lets the engine use the capture's observed pacing
            if str(fields.get("thinktime", "")).strip():
                config["thinktime"] = _clamp(fields.get("thinktime"), 0, _MAX_THINKTIME_MS, 500)
            # New reasoning engine → runnable JMX + parameter CSVs + downloadable bundle.
            result = analyze(upload)
            result_id = uuid.uuid4().hex[:10]
            jmx_path, csv_paths, report_paths = emit_jmx(result, OUTPUT_DIR, config, name=f"har2jmx_{result_id}")

            bundle_path = OUTPUT_DIR / f"har2jmx_{result_id}.zip"
            with zipfile.ZipFile(bundle_path, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.write(jmx_path, arcname=jmx_path.name)
                for c in csv_paths:
                    zf.write(c, arcname=c.name)
                for rp in report_paths:
                    zf.write(rp, arcname=rp.name)

            _prune_output(OUTPUT_DIR, _keep_results())   # bound the output dir (newest bundles kept)

            downloads = {
                "jmx": jmx_path.name,
                "zip": bundle_path.name,
                "csvs": [c.name for c in csv_paths],
                "reports": [rp.name for rp in report_paths],
            }
            payload = build_web_summary(result, result_id, downloads)
            payload["config"] = config
            self.respond_json(payload)
        except ValueError as exc:
            # intentional input-validation errors (no file, malformed/invalid HAR) — the message is
            # user-actionable and safe to show.
            self.respond_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
        except Exception:
            # unexpected failure: never echo internal exception detail (paths, stack info) to the
            # client — log the real cause server-side and return a generic message.
            traceback.print_exc()
            self.respond_json(
                {"error": "Could not process this HAR. Please verify it is a valid capture and try again."},
                status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def serve_download(self, filename: str) -> None:
        safe = Path(filename).name
        path = OUTPUT_DIR / safe
        if not path.exists():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Disposition", f'attachment; filename="{escape(safe)}"')
        self.send_header("Content-Length", str(path.stat().st_size))
        self.end_headers()
        self.wfile.write(path.read_bytes())

    def respond_json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def _lan_ip() -> str:
    """Best-effort local network IP so others on the LAN know the address to open."""
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))          # no packet is sent; just picks the outbound interface
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def main() -> None:
    import os
    host = os.environ.get("HAR2JMX_HOST", "127.0.0.1")
    try:
        port = int(os.environ.get("HAR2JMX_PORT", "8000"))
    except ValueError:
        port = 8000

    handler = functools.partial(AppHandler, directory=str(ROOT))
    server = ThreadingHTTPServer((host, port), handler)

    print(f"har2jmx running — local:   http://127.0.0.1:{port}")
    if host not in ("127.0.0.1", "localhost"):
        # exposed on the network: show the address teammates on the same LAN can open
        print(f"                shared:  http://{_lan_ip()}:{port}   (anyone on your network)")
        print("                (bound to all interfaces — allow the port through your firewall if prompted)")
    else:
        print("                (localhost only — set HAR2JMX_HOST=0.0.0.0 to let others on your network use it)")
    server.serve_forever()


if __name__ == "__main__":
    main()
