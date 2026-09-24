"""Local capture sink: the browser pane POSTs a real capture payload here and it lands on disk.

Runs on 127.0.0.1 only. 127.0.0.1 is a "potentially trustworthy" origin, so an https page may POST to
it without mixed-content blocking; permissive CORS is returned so the page's fetch succeeds. This exists
purely so full-fidelity REAL captures reach disk without being retyped (no fidelity loss, no invention).
"""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

OUT = Path(__file__).resolve().parents[1] / "raw"
OUT.mkdir(parents=True, exist_ok=True)


class Handler(BaseHTTPRequestHandler):
    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        # Chrome Private Network Access: a public https origin may only reach a private address
        # (127.0.0.1) when the preflight explicitly opts in.
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.send_header("Access-Control-Max-Age", "86400")

    def do_OPTIONS(self) -> None:          # noqa: N802
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self) -> None:              # noqa: N802
        self.send_response(200)
        self._cors()
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"capture-sink alive")

    def do_POST(self) -> None:             # noqa: N802
        q = parse_qs(urlparse(self.path).query)
        name = (q.get("name") or ["capture"])[0]
        name = "".join(c for c in name if c.isalnum() or c in "-_")[:80] or "capture"
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length)
        path = OUT / f"{name}.capture.json"
        path.write_bytes(body)
        try:
            n = len(json.loads(body).get("entries", []))
        except Exception:  # noqa: BLE001
            n = -1
        self.send_response(200)
        self._cors()
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"ok": True, "file": str(path), "entries": n}).encode())
        print(f"[sink] wrote {path.name} ({len(body)} bytes, {n} entries)", flush=True)

    def log_message(self, *a) -> None:     # quiet
        return


if __name__ == "__main__":
    print("[sink] listening on http://127.0.0.1:8899 ->", OUT, flush=True)
    HTTPServer(("127.0.0.1", 8899), Handler).serve_forever()
