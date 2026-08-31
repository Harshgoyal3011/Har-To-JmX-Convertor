from __future__ import annotations

import functools
import json
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


def _clamp(raw: str, minimum: int, default: int) -> str:
    try:
        return str(max(minimum, int(str(raw).strip())))
    except (TypeError, ValueError):
        return str(default)


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
            upload, fields = parse_multipart(self.headers, self.rfile.read(length))
            config = {
                "threads": _clamp(fields.get("threads", "10"), 1, 10),
                "loops": _clamp(fields.get("loops", "1"), 1, 1),
                "ramp": _clamp(fields.get("ramp", "5"), 0, 5),
                "thinktime": _clamp(fields.get("thinktime", "500"), 0, 500),
            }
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

            downloads = {
                "jmx": jmx_path.name,
                "zip": bundle_path.name,
                "csvs": [c.name for c in csv_paths],
                "reports": [rp.name for rp in report_paths],
            }
            payload = build_web_summary(result, result_id, downloads)
            payload["config"] = config
            self.respond_json(payload)
        except Exception as exc:
            self.respond_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)

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


def main() -> None:
    handler = functools.partial(AppHandler, directory=str(ROOT))
    server = ThreadingHTTPServer(("127.0.0.1", 8000), handler)
    print("Self Healing HAR to JMeter prototype running at http://127.0.0.1:8000")
    server.serve_forever()


if __name__ == "__main__":
    main()
