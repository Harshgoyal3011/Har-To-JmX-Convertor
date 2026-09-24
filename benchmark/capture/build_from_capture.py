"""Turn a REAL capture record (benchmark/raw/*.capture.json) into a normalized HAR.

Capture record schema (all values observed in the browser pane; nothing invented):
{
  "meta": {app, domain, flow, source, notes, think_gap_ms?, phase2_start_ms?},
  "rows": ["initiatorType|startTimeMs|durationMs|transferSize|url", ...],   # Resource Timing
  "api":  [{"u":url, "st":startMs, "d":durMs, "status":int, "b":responseBody,
            "method":"GET", "reqBody":null, "mime":null}, ...]              # real fetch responses
}
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from har_builder import write_har  # noqa: E402

BENCH = Path(__file__).resolve().parents[1]


def build(record: dict, out_name: str) -> tuple[Path, int, int]:
    meta = record["meta"]
    entries: list[dict] = []

    for line in record.get("rows", []):
        t, st, d, s, url = line.split("|", 4)
        entries.append({"u": url, "t": t, "st": int(st), "d": int(d), "s": int(s), "p": "h2",
                        "method": "GET", "status": 200})

    for a in record.get("api", []):
        entries.append({
            "u": a["u"], "t": "fetch", "st": int(a.get("st", 0)), "d": int(a.get("d", 1)) or 1,
            "s": len(a.get("b") or ""), "p": "h2", "method": a.get("method", "GET"),
            "status": int(a.get("status", 200)),
            "mime": a.get("mime") or "application/json", "body": a.get("b"),
            "reqBody": a.get("reqBody"), "reqMime": a.get("reqMime"),
            "reqHeaders": a.get("reqHeaders"),
        })

    # optional, DISCLOSED compression of an instrumentation gap into a realistic think time
    p2 = meta.get("phase2_start_ms")
    gap = meta.get("think_gap_ms")
    if p2 and gap:
        phase1_end = max((e["st"] + e["d"] for e in entries if e["st"] < p2), default=0)
        for e in entries:
            if e["st"] >= p2:
                e["st"] = phase1_end + gap + (e["st"] - p2)

    entries.sort(key=lambda e: e["st"])
    for prev, cur in zip(entries, entries[1:]):
        prev["gap"] = max(0, cur["st"] - prev["st"] - prev["d"])

    return write_har({"entries": entries}, BENCH / "normalized" / out_name,
                     app=meta["app"], domain=meta["domain"], flow=meta["flow"],
                     source=meta["source"], notes=meta.get("notes", ""),
                     provenance=meta.get("provenance", "REAL_BROWSER_CAPTURE"))


def main() -> None:
    raw = sorted((BENCH / "raw").glob("*.capture.json"))
    for p in raw:
        rec = json.loads(p.read_text(encoding="utf-8"))
        if "meta" not in rec:
            continue                                   # app01 uses its own bespoke builder
        out, n, hosts = build(rec, p.name.replace(".capture.json", ".har"))
        print(f"built {out.name}: {n} entries, {hosts} hosts")


if __name__ == "__main__":
    main()
