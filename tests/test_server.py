"""Web-server hardening tests (stdlib http.server adapter)."""
from __future__ import annotations

import functools
import http.client
import os
import re
import socket
import threading
from http.server import ThreadingHTTPServer

import tempfile
import time
from pathlib import Path

from har2jmx.paths import ROOT
from har2jmx.server.handler import (
    AppHandler,
    _clamp,
    _keep_results,
    _max_upload_bytes,
    _prune_output,
)


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
        assert _max_upload_bytes() == 250 * 1024 * 1024          # default 250 MB
        os.environ["HAR2JMX_MAX_UPLOAD_MB"] = "5"
        assert _max_upload_bytes() == 5 * 1024 * 1024           # env override
        os.environ["HAR2JMX_MAX_UPLOAD_MB"] = "not-a-number"
        assert _max_upload_bytes() == 250 * 1024 * 1024          # bad value → default
    finally:
        if old is None:
            os.environ.pop("HAR2JMX_MAX_UPLOAD_MB", None)
        else:
            os.environ["HAR2JMX_MAX_UPLOAD_MB"] = old


def test_clamp_enforces_floor_ceiling_and_default():
    assert _clamp("50", 1, 2000, 10) == "50"      # in range → unchanged
    assert _clamp("0", 1, 2000, 10) == "1"        # below floor → floor
    assert _clamp("999999", 1, 2000, 10) == "2000"  # above ceiling → ceiling (no million threads)
    assert _clamp("junk", 1, 2000, 10) == "10"    # unparseable → default
    assert _clamp("", 0, 100, 5) == "5"           # empty → default


def test_prune_output_keeps_newest_bundles_only():
    # a conversion writes several files under one har2jmx_<id> prefix; pruning ages out whole bundles,
    # keeps the newest N, and never touches .gitkeep or unrelated files.
    with tempfile.TemporaryDirectory() as d:
        out = Path(d)
        (out / ".gitkeep").write_text("")
        (out / "notes.txt").write_text("keep me")           # unrelated file
        ids = [f"{i:010x}" for i in range(5)]               # 5 result bundles, oldest -> newest
        base = time.time() - 1000
        for n, rid in enumerate(ids):
            for ext in (".jmx", ".zip", "_auth.csv"):
                f = out / f"har2jmx_{rid}{ext}"
                f.write_text("x")
                os.utime(f, (base + n, base + n))           # stagger mtime so order is deterministic

        _prune_output(out, keep=2)

        remaining = {p.name for p in out.iterdir()}
        assert ".gitkeep" in remaining and "notes.txt" in remaining      # protected files survive
        surviving_ids = {m.group(1) for p in out.iterdir()
                         if (m := re.match(r"har2jmx_([0-9a-f]{10})", p.name))}
        assert surviving_ids == {ids[3], ids[4]}, surviving_ids          # only the newest 2 bundles
        assert not any(ids[0] in p.name for p in out.iterdir())          # oldest fully removed


def test_keep_results_env():
    old = os.environ.get("HAR2JMX_KEEP_RESULTS")
    try:
        os.environ.pop("HAR2JMX_KEEP_RESULTS", None)
        assert _keep_results() == 50
        os.environ["HAR2JMX_KEEP_RESULTS"] = "3"
        assert _keep_results() == 3
        os.environ["HAR2JMX_KEEP_RESULTS"] = "junk"
        assert _keep_results() == 50
    finally:
        if old is None:
            os.environ.pop("HAR2JMX_KEEP_RESULTS", None)
        else:
            os.environ["HAR2JMX_KEEP_RESULTS"] = old


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
            "Content-Length: 999999999\r\n"       # ~953 MB, far over the 250 MB limit
            "\r\n"
        )
        s.sendall(req.encode())
        status_line = s.recv(256).decode("latin-1", "replace").split("\r\n", 1)[0]
        s.close()
        assert "413" in status_line, status_line
    finally:
        srv.shutdown()


def _post_har(port, harfile_bytes):
    boundary = "----harbnd"
    body = (
        f'--{boundary}\r\n'
        'Content-Disposition: form-data; name="harfile"; filename="c.har"\r\n\r\n'
    ).encode() + harfile_bytes + f"\r\n--{boundary}--\r\n".encode()
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    c.request("POST", "/api/convert", body=body,
              headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    r = c.getresponse()
    return r.status, r.read().decode("utf-8", "replace")


def test_invalid_har_returns_400_with_message():
    srv, port = _start()
    try:
        status, body = _post_har(port, b"this is not json")   # invalid HAR -> ValueError
        assert status == 400, status
        assert "error" in body
    finally:
        srv.shutdown()


def test_unexpected_error_is_generic_500_without_leaking():
    # an internal (non-ValueError) failure must NOT echo its message to the client.
    import har2jmx.server.handler as H

    def boom(*_a, **_k):
        raise RuntimeError("INTERNAL-LEAK-XYZ /secret/path")

    orig, H.analyze = H.analyze, boom
    srv, port = _start()
    try:
        status, body = _post_har(port, b'{"log":{"entries":[]}}')
        assert status == 500, status
        assert "INTERNAL-LEAK-XYZ" not in body and "/secret/path" not in body, "internal detail leaked!"
        assert "error" in body                                 # generic message still returned
    finally:
        H.analyze = orig
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
