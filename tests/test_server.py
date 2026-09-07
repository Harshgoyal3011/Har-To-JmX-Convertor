"""Web-server hardening tests (stdlib http.server adapter)."""
from __future__ import annotations

import functools
import http.client
import os
import socket
import threading
from http.server import ThreadingHTTPServer

from har2jmx.paths import ROOT
from har2jmx.server.handler import AppHandler, _max_upload_bytes


def _start():
    handler = functools.partial(AppHandler, directory=str(ROOT))
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, port


def test_max_upload_bytes_default_and_env():
    old = os.environ.get("HAR2JMX_MAX_UPLOAD_MB")
    try:
        os.environ.pop("HAR2JMX_MAX_UPLOAD_MB", None)
        assert _max_upload_bytes() == 25 * 1024 * 1024          # default 25 MB
        os.environ["HAR2JMX_MAX_UPLOAD_MB"] = "5"
        assert _max_upload_bytes() == 5 * 1024 * 1024           # env override
        os.environ["HAR2JMX_MAX_UPLOAD_MB"] = "not-a-number"
        assert _max_upload_bytes() == 25 * 1024 * 1024          # bad value → default
    finally:
        if old is None:
            os.environ.pop("HAR2JMX_MAX_UPLOAD_MB", None)
        else:
            os.environ["HAR2JMX_MAX_UPLOAD_MB"] = old


def test_oversized_upload_rejected_before_read():
    # a huge Content-Length must be refused with 413 WITHOUT the server reading the (unsent) body,
    # so a hostile multi-GB upload can't exhaust memory. We send only headers via a raw socket.
    srv, port = _start()
    try:
        s = socket.create_connection(("127.0.0.1", port), timeout=5)
        req = (
            "POST /api/convert HTTP/1.1\r\n"
            "Host: 127.0.0.1\r\n"
            "Content-Type: multipart/form-data; boundary=xx\r\n"
            "Content-Length: 999999999\r\n"       # ~953 MB, far over the 25 MB limit
            "\r\n"
        )
        s.sendall(req.encode())
        status_line = s.recv(256).decode("latin-1", "replace").split("\r\n", 1)[0]
        s.close()
        assert "413" in status_line, status_line
    finally:
        srv.shutdown()


def test_index_and_unknown_post():
    srv, port = _start()
    try:
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        c.request("GET", "/")
        assert c.getresponse().status == 200               # app UI served
        c.request("POST", "/nope")
        assert c.getresponse().status == 404               # unknown POST route
    finally:
        srv.shutdown()


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for fn in fns:
        try:
            fn()
        except AssertionError as e:
            print(f"FAIL  {fn.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            print(f"ERROR {fn.__name__}: {type(e).__name__}: {e}")
        else:
            passed += 1
            print(f"ok    {fn.__name__}")
    print(f"\n{passed}/{len(fns)} passed")
    raise SystemExit(0 if passed == len(fns) else 1)
