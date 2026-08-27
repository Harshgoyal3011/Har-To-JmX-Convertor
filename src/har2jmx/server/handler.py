from __future__ import annotations

import functools
import json
from html import escape
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from har2jmx.paths import OUTPUT_DIR, ROOT
from har2jmx.pipeline_v2 import convert_har_v2
from har2jmx.reports import build_summary
from har2jmx.server.multipart import parse_multipart


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
                "threads": fields.get("threads", "1"),
                "loops": fields.get("loops", "1"),
                "ramp": fields.get("ramp", "1"),
                "clearCookies": fields.get("clearCookies", "false"),
            }
            # Use new pipeline with AI review layer
            result = convert_har_v2(upload, config)
            payload = build_summary(result)
            payload.update({
                "threads": result.thread_count,
                "loops": result.loops,
                "ramp": result.ramp_time,
                "clearCookies": result.clear_cookies,
            })
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
