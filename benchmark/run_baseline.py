"""Phase 3 baseline runner — runs the CURRENT converter over every corpus HAR and records raw metrics.

Does NOT modify the converter. One HAR's crash never stops the run. Every row is tagged with its
provenance bucket so REAL captures are never merged with SYNTHETIC fixtures.

Buckets:
  REAL_CAPTURE  benchmark/normalized/*.har   - real browser captures (this benchmark)
  REAL_API      examples/*.har hitting real public API hosts (hand-authored probe, real endpoints)
  SYNTHETIC     examples/*.har + tests/fixtures/*.har on *.example.com (hand-authored)
"""
from __future__ import annotations

import csv
import json
import sys
import time
import traceback
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from har2jmx.emit import build_jmx_xml, validate_plan          # noqa: E402
from har2jmx.engine import analyze                             # noqa: E402

BENCH = ROOT / "benchmark"
RAW_RESULTS = BENCH / "RAW_RESULTS"

REAL_API_HOSTS = {
    "gorest.co.in", "jsonplaceholder.typicode.com", "dummyjson.com", "api.escuelajs.co",
    "restcountries.com", "rickandmortyapi.com", "openlibrary.org", "swapi.info",
    "petstore3.swagger.io", "restful-booker.herokuapp.com", "fakestoreapi.com",
}


def _hosts(har: dict) -> set[str]:
    out = set()
    for e in har.get("log", {}).get("entries", []):
        try:
            out.add(urlparse(e["request"]["url"]).netloc)
        except Exception:  # noqa: BLE001
            pass
    return out


def bucket_of(path: Path, har: dict) -> str:
    try:
        comment = json.loads(har.get("log", {}).get("comment") or "{}")
        prov = comment.get("provenance")
        if prov == "REAL_BROWSER_CAPTURE":
            return "REAL_CAPTURE"
        if prov == "REAL_API_JOURNEY":
            return "REAL_API_JOURNEY"
    except Exception:  # noqa: BLE001
        pass
    hosts = _hosts(har)
    if hosts & REAL_API_HOSTS:
        return "REAL_API"
    return "SYNTHETIC"


def corpus() -> list[Path]:
    paths = sorted((BENCH / "normalized").glob("*.har"))
    paths += sorted((ROOT / "examples").glob("*.har"))
    paths += sorted((ROOT / "tests" / "fixtures").glob("*.har"))
    return paths


def measure(path: Path) -> dict:
    row: dict = {"har": path.name, "path": str(path.relative_to(ROOT))}
    try:
        data = path.read_bytes()
        har = json.loads(data)
        row["bucket"] = bucket_of(path, har)
        row["har_requests"] = len(har.get("log", {}).get("entries", []))
        row["har_hosts"] = len(_hosts(har))
        meta = {}
        try:
            meta = json.loads(har.get("log", {}).get("comment") or "{}")
        except Exception:  # noqa: BLE001
            pass
        row["application"] = meta.get("application", path.stem)
        row["domain"] = meta.get("domain", "")
        row["flow"] = meta.get("flow", "")
    except Exception as exc:  # noqa: BLE001
        row.update(conversion="FAIL", crash=f"{type(exc).__name__}: {exc}", stage="read")
        return row

    t0 = time.perf_counter()
    try:
        res = analyze(data)
    except Exception as exc:  # noqa: BLE001
        row.update(conversion="FAIL", crash=f"{type(exc).__name__}: {exc}", stage="analyze",
                   traceback=traceback.format_exc()[-1200:],
                   conversion_time=round(time.perf_counter() - t0, 3))
        return row
    try:
        xml = build_jmx_xml(res).decode()
    except Exception as exc:  # noqa: BLE001
        row.update(conversion="FAIL", crash=f"{type(exc).__name__}: {exc}", stage="emit",
                   traceback=traceback.format_exc()[-1200:],
                   conversion_time=round(time.perf_counter() - t0, 3))
        return row
    elapsed = time.perf_counter() - t0

    kept = [r for r in res.capture.requests if not r.classification.excluded]
    excluded = [r for r in res.capture.requests if r.classification.excluded]
    ok_extractors = {c.value for c in res.extractor_checks if c.ok}
    csv_cols = [c.name for d in res.parameterization.datasets for c in d.columns]
    try:
        problems = validate_plan(res, xml)
    except Exception:  # noqa: BLE001
        problems = ["validate_plan raised"]

    row.update(
        conversion="PASS", crash="", stage="", conversion_time=round(elapsed, 3),
        samplers=xml.count("HTTPSamplerProxy") // 2 if xml.count("HTTPSamplerProxy") else 0,
        transactions=len(getattr(res, "transactions", []) or []),
        kept_requests=len(kept), excluded_requests=len(excluded),
        assertions=xml.count('testname="Assert Response Code (2xx/3xx)"'),
        correlations=len(res.correlations),
        correlations_verified=sum(1 for c in res.correlations if c.value in ok_extractors),
        correlation_vars=[c.variable for c in res.correlations],
        csv_columns=csv_cols, csv_column_count=len(csv_cols),
        review_items=len(res.classification.needs_correlation()),
        unknown_values=len(res.classification.unknowns()),
        validate_problems=len(problems), validate_detail=problems[:5],
        kept_urls=[f"{r.request.method} {r.request.url}" for r in kept][:40],
        excluded_hosts=sorted({r.request.host for r in excluded}),
        jmx_bytes=len(xml),
    )
    return row


def main() -> None:
    RAW_RESULTS.mkdir(parents=True, exist_ok=True)
    rows = []
    for p in corpus():
        row = measure(p)
        rows.append(row)
        (RAW_RESULTS / f"{p.stem}.json").write_text(json.dumps(row, indent=1), encoding="utf-8")
        flag = "OK " if row.get("conversion") == "PASS" else "FAIL"
        print(f"[{flag}] {row['bucket']:12} {p.name:46} "
              f"req={row.get('har_requests','?'):>4} kept={row.get('kept_requests','?'):>3} "
              f"txn={row.get('transactions','?'):>3} corr={row.get('correlations','?'):>3} "
              f"csv={row.get('csv_column_count','?'):>3} {row.get('crash','')}")

    (BENCH / "baseline_rows.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")

    cols = ["bucket", "application", "domain", "flow", "har", "har_requests", "har_hosts",
            "conversion", "conversion_time", "crash", "transactions", "samplers", "assertions",
            "kept_requests", "excluded_requests", "correlations", "correlations_verified",
            "csv_column_count", "review_items", "validate_problems"]
    with (BENCH / "APPLICATION_SCORECARD.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)

    n = len(rows)
    ok = sum(1 for r in rows if r.get("conversion") == "PASS")
    print(f"\nHARs: {n}   conversion PASS: {ok} ({ok/n*100:.1f}%)   FAIL: {n-ok}")
    for b in ("REAL_CAPTURE", "REAL_API_JOURNEY", "REAL_API", "SYNTHETIC"):
        sub = [r for r in rows if r.get("bucket") == b]
        if not sub:
            continue
        okb = sum(1 for r in sub if r.get("conversion") == "PASS")
        corr = sum(r.get("correlations", 0) or 0 for r in sub)
        csvc = sum(r.get("csv_column_count", 0) or 0 for r in sub)
        print(f"  {b:12} n={len(sub):3} pass={okb:3} correlations={corr:4} csv_cols={csvc:4}")


if __name__ == "__main__":
    main()
