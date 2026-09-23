"""Automated release gates for the HAR->JMX converter.

Pure, importable functions that inspect the ACTUAL generated JMX/CSV (plus the EngineResult) and return
release verdicts. Reuses the existing validator (`har2jmx.emit.validate.validate_plan`) rather than
duplicating discovery logic. Run as a module to print the Part-20 release checklist over the repo corpus.
"""
from __future__ import annotations

import glob
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from xml.dom import minidom

from har2jmx.classify import ValueClass
from har2jmx.emit import build_jmx_xml, validate_plan
from har2jmx.engine import analyze

_UDV = {"THREADS", "LOOPS", "RAMP", "THINKTIME", "BASE_URL", "PROTOCOL", "HOLD", "DURATION", "TIMEOUT"}
_ROOT = Path(__file__).parent.parent
_STATIC_EXT = (".css", ".js", ".png", ".jpg", ".gif", ".svg", ".woff", ".woff2", ".ico", ".map")


# ---------------------------------------------------------------- JMX parsing (single source of truth)

def _elems(n):
    return [c for c in n.childNodes if c.nodeType == c.ELEMENT_NODE]


def _rc_assertions(container):
    """Response-CODE assertions (2xx/3xx) that are DIRECT children of `container`."""
    kids = _elems(container)
    out, i = [], 0
    while i < len(kids):
        e = kids[i]
        ht = kids[i + 1] if i + 1 < len(kids) and kids[i + 1].tagName == "hashTree" else None
        if e.tagName == "ResponseAssertion" and "Assertion.response_code" in e.toxml():
            out.append(e)
        i += 2 if ht is not None else 1
    return out


def _rc_assertions_deep(container):
    """Response-CODE assertions (2xx/3xx) anywhere in `container`'s subtree (the assertion now nests
    under the transaction's anchor sampler, not as a direct child of the Transaction Controller)."""
    out = []
    for n in container.getElementsByTagName("ResponseAssertion"):
        if "Assertion.response_code" in n.toxml():
            out.append(n)
    return out


def _thread_group_ht(doc):
    box = [None]

    def find(c):
        kids = _elems(c)
        i = 0
        while i < len(kids):
            e = kids[i]
            ht = kids[i + 1] if i + 1 < len(kids) and kids[i + 1].tagName == "hashTree" else None
            if e.tagName == "ThreadGroup" and ht is not None:
                box[0] = ht
                return
            if e.tagName == "hashTree":
                find(e)
            elif ht is not None:
                find(ht)
            i += 2 if ht is not None else 1
    find(doc.documentElement)
    return box[0]


@dataclass
class ParsedPlan:
    xml: str
    csv_cols: list
    jvars: set
    extractor_vars: set
    sampler_paths: list
    tg_assertions: int
    tc_assertion_counts: list
    thinktime_count: int
    txn_count: int
    bare_tg_timer: bool
    scoped_timer: bool
    total_rc_assertions: int


def parse_plan(xml: str) -> ParsedPlan:
    doc = minidom.parseString(xml)
    tg = _thread_group_ht(doc)
    tg_assertions = len(_rc_assertions(tg)) if tg is not None else 0
    tc_counts, tt, txns, bare = [], 0, 0, False
    if tg is not None:
        kids = _elems(tg)
        i = 0
        while i < len(kids):
            e = kids[i]
            ht = kids[i + 1] if i + 1 < len(kids) and kids[i + 1].tagName == "hashTree" else None
            if e.tagName == "TransactionController" and ht is not None:
                txns += 1
                tc_counts.append(len(_rc_assertions_deep(ht)))   # assertion nests under the anchor sampler
            elif e.tagName == "TestAction" and "Think Time" in e.getAttribute("testname"):
                tt += 1
            elif e.tagName in ("ConstantTimer", "UniformRandomTimer"):
                bare = True
            i += 2 if ht is not None else 1
    cols = []
    for names in re.findall(r'variableNames">([^<]+)<', xml):
        cols += [c.strip() for c in names.split(",") if c.strip()]
    jvars = set(re.findall(r"\$\{(\w+)\}", xml)) - _UDV
    extractor_vars = set(re.findall(r'referenceNames">([^<]+)<', xml)) | \
        set(re.findall(r'RegexExtractor\.refname">([^<]+)<', xml))
    sampler_paths = re.findall(r'HTTPSampler\.path">([^<]*)<', xml)
    scoped = bool(re.search(r'testclass="TestAction".*?<hashTree>\s*<UniformRandomTimer', xml, re.S))
    total_rc = xml.count('testname="Assert Response Code (2xx/3xx)"')
    return ParsedPlan(xml, cols, jvars, extractor_vars, sampler_paths, tg_assertions, tc_counts,
                      tt, txns, bare, scoped, total_rc)


# ---------------------------------------------------------------- gates

@dataclass
class GateResult:
    name: str
    passed: bool
    detail: str


def evaluate(res, xml: str, config: dict | None = None) -> list[GateResult]:
    """Run every per-artifact gate against one generated plan. Returns a list of GateResult."""
    p = parse_plan(xml)
    out: list[GateResult] = []

    def g(name, ok, detail=""):
        out.append(GateResult(name, bool(ok), detail))

    # Part 6 — JMX structural
    g("no Thread-Group response assertion", p.tg_assertions == 0, f"tg_level={p.tg_assertions}")
    g("exactly one assertion per Transaction Controller",
      all(n == 1 for n in p.tc_assertion_counts) and (p.txn_count == 0 or len(p.tc_assertion_counts) > 0),
      f"per_txn={p.tc_assertion_counts}")
    g("no per-sampler assertion duplication", p.total_rc_assertions == p.txn_count,
      f"assertions={p.total_rc_assertions},txns={p.txn_count}")

    # noise / performance-relevance (Part 11): a host that is ONLY ever excluded must not reach the JMX,
    # and an excluded-only path must not become a sampler.
    kept_hosts = {r.request.host for r in res.capture.requests if not r.classification.excluded}
    excl_hosts = {r.request.host for r in res.capture.requests if r.classification.excluded}
    noise_only = {h for h in (excl_hosts - kept_hosts) if h}
    leaked_hosts = sorted(h for h in noise_only if h in xml)
    g("no noise-only third-party host in JMX", not leaked_hosts, f"leaked={leaked_hosts}")
    kept_paths = {r.request.path for r in res.capture.requests if not r.classification.excluded}
    excl_only_paths = {r.request.path for r in res.capture.requests
                       if r.classification.excluded and r.request.path not in kept_paths}
    leaked_paths = sorted(pp for pp in excl_only_paths if pp in p.sampler_paths)
    g("no excluded request path became a sampler", not leaked_paths, f"leaked={leaked_paths}")
    g("no static asset sampler", not [sp for sp in p.sampler_paths if sp.lower().endswith(_STATIC_EXT)],
      f"static_samplers={[sp for sp in p.sampler_paths if sp.lower().endswith(_STATIC_EXT)]}")

    # Part 8 — CSV
    unref = sorted(set(p.csv_cols) - p.jvars)
    g("every CSV column referenced by a ${var}", not unref, f"unreferenced={unref}")
    g("no duplicate CSV variable names", len(p.csv_cols) == len(set(p.csv_cols)),
      f"dups={[c for c in set(p.csv_cols) if p.csv_cols.count(c) > 1]}")
    by_val = {v.value: v for v in res.classification.verdicts}
    runtime_in_csv = []
    for d in res.parameterization.datasets:
        for c in d.columns:
            sample = str(d.rows[0].get(c.name, "")) if d.rows else ""
            verd = by_val.get(sample)
            if verd is not None and verd.classification == ValueClass.RUNTIME_GENERATED:
                runtime_in_csv.append(c.name)
    g("no server-generated (runtime) value in CSV", not runtime_in_csv, f"runtime_cols={runtime_in_csv}")

    # Part 7/10 — correlation producer/consumer + verified extractor + no stale literal
    chk_by_var = {c.variable: c for c in res.extractor_checks}
    bad_corr = []
    for c in res.correlations:
        from har2jmx.correlate import ExtractorType
        if c.extractor == ExtractorType.COOKIE_MANAGER:
            continue                                   # replayed by the Cookie Manager, no ${var}
        chk = chk_by_var.get(c.variable)
        emitted = (f"${{{c.variable}}}" in xml)
        if emitted and (not c.consumers or (chk is not None and not chk.ok)):
            bad_corr.append(c.variable)
    g("every emitted correlation has producer+consumer+verified extractor", not bad_corr,
      f"bad={bad_corr}")

    # Correlation-application gate (Phase E): a correlation whose extractor is VERIFIED UNIQUE and whose
    # value is substitutable and has consumers MUST have its ${var} applied to a consumer. This is the
    # positive invariant for a *genuine* emission bug (verified but never applied) — distinct from the
    # gate above (emitted-but-no-consumer / unverified) and from validate_plan's "literal shipped" check
    # (which is a broader substring test). Unverifiable extractors are intentional safe-drops, not defects.
    from har2jmx.validate import ExtractorStatus
    from har2jmx.emit.jmx import _sub_ok
    unapplied = []
    for c in res.correlations:
        if c.extractor == ExtractorType.COOKIE_MANAGER:
            continue
        chk = chk_by_var.get(c.variable)
        if (chk is not None and chk.ok and chk.status == ExtractorStatus.UNIQUE
                and c.consumers and _sub_ok(str(c.value)) and f"${{{c.variable}}}" not in xml):
            unapplied.append(c.variable)
    g("verified-unique correlation is applied to a consumer (${var} present)", not unapplied,
      f"unapplied={unapplied}")

    # Part 9 — think time between transactions, correctly scoped
    g("think time strictly between transactions (N-1)",
      p.thinktime_count == max(p.txn_count - 1, 0), f"tt={p.thinktime_count},txn={p.txn_count}")
    g("think time not a bare Thread-Group timer", not p.bare_tg_timer, f"bare_timer={p.bare_tg_timer}")
    g("think time timer scoped to a Test Action",
      p.thinktime_count == 0 or p.scoped_timer, f"scoped={p.scoped_timer}")

    # Part 8 (reverse) — validator is clean (unresolved vars, unused CSV, literal secret, empty dataset)
    issues = validate_plan(res, xml)
    g("validate_plan clean (no unresolved vars / leaks / unused CSV)", not issues, f"issues={issues}")

    return out


def determinism_gate(har: bytes, config: dict | None = None) -> GateResult:
    a = build_jmx_xml(analyze(har), config or {"threads": "10"})
    b = build_jmx_xml(analyze(har), config or {"threads": "10"})
    return GateResult("deterministic JMX (byte-identical across runs)", a == b,
                      "identical" if a == b else "differs")


def conversion_safety_gate(har: bytes, config: dict | None = None) -> GateResult:
    """RC-2: conversion must SUCCEED with well-formed XML, or fail with a controlled ValueError — it must
    never raise an uncaught parser exception (e.g. ExpatError on XML-1.0-illegal control chars)."""
    try:
        res = analyze(har)
        xml = build_jmx_xml(res, config or {"threads": "10"})
        minidom.parseString(xml)                       # must be well-formed
        return GateResult("conversion safety (valid JMX or clean error, never a crash)", True, "valid JMX")
    except ValueError as exc:                           # controlled, user-safe failure is acceptable
        return GateResult("conversion safety (valid JMX or clean error, never a crash)", True,
                          f"clean error: {str(exc)[:60]}")
    except Exception as exc:                            # noqa: BLE001 — any uncaught non-ValueError is a defect
        return GateResult("conversion safety (valid JMX or clean error, never a crash)", False,
                          f"UNCAUGHT {type(exc).__name__}: {str(exc)[:80]}")


def repo_architecture_gates(src_root: Path | None = None) -> list[GateResult]:
    """Part 1-3: prove a single canonical pipeline with no duplicate active engines on this baseline."""
    src = src_root or (_ROOT / "src" / "har2jmx")
    out = []
    out.append(GateResult("single pipeline (no spec/ second-engine dir)",
                          not (src / "spec").exists(), f"spec_exists={(src / 'spec').exists()}"))
    dup = []
    for pat in ("discover_enhanced", "build_value_model_independent", "build_performance_spec"):
        hits = [str(p) for p in src.rglob("*.py") if pat in p.read_text(encoding="utf-8", errors="ignore")]
        if hits:
            dup.append(pat)
    out.append(GateResult("no duplicate discovery/spec engines", not dup, f"found={dup}"))
    return out


# ---------------------------------------------------------------- corpus runner + Part-20 checklist

@dataclass
class CorpusResult:
    tag: str
    total: int = 0
    passed: int = 0
    failures: list = field(default_factory=list)   # (har_name, gate_name, detail)


def run_corpus(hars: list[tuple[str, bytes]], tag: str, config: dict | None = None) -> CorpusResult:
    cr = CorpusResult(tag=tag)
    for name, data in hars:
        try:
            res = analyze(data)
            xml = build_jmx_xml(res, config or {"threads": "10"}).decode()
        except Exception as ex:  # noqa: BLE001
            cr.total += 1
            cr.failures.append((name, "analyze/emit", str(ex)[:80]))
            continue
        for gr in evaluate(res, xml, config):
            cr.total += 1
            if gr.passed:
                cr.passed += 1
            else:
                cr.failures.append((name, gr.name, gr.detail))
    return cr


def _load(paths):
    return [(Path(p).name, Path(p).read_bytes()) for p in paths]


_REAL_PUBLIC_API = {"dummyjson", "library_openlibrary", "retail_fakestore", "ecommerce_platzi",
                    "petretail_petstore", "restful_booker", "content_jsonplaceholder",
                    "graphql_rickandmorty", "genai_assistant"}


def run_release_checklist(config: dict | None = None) -> tuple[list[GateResult], dict]:
    """Aggregate all gates over the tagged corpus and return (checklist, buckets)."""
    example_hars = sorted(glob.glob(str(_ROOT / "examples" / "*.har")))
    real = _load([p for p in example_hars if Path(p).stem in _REAL_PUBLIC_API])
    synth_examples = _load([p for p in example_hars if Path(p).stem not in _REAL_PUBLIC_API])
    fixtures = _load(sorted(glob.glob(str(_ROOT / "tests" / "fixtures" / "*.har"))))

    buckets = {
        "REAL-public-API": run_corpus(real, "REAL-public-API", config),
        "SYNTHETIC-fixture": run_corpus(synth_examples + fixtures, "SYNTHETIC-fixture", config),
    }
    # SYNTHETIC-corpus (the ~100 scenarios)
    try:
        import corpus_synthetic as cs
        scen, rows = cs.run()
        cfails = [(sid, label, detail) for sid, arch, label, ok, detail in rows if not ok]
        buckets["SYNTHETIC-corpus"] = CorpusResult("SYNTHETIC-corpus", len(rows), len(rows) - len(cfails), cfails)
    except Exception as ex:  # noqa: BLE001
        buckets["SYNTHETIC-corpus"] = CorpusResult("SYNTHETIC-corpus", 0, 0, [("corpus", "load", str(ex)[:80])])

    corpus_ok = all(b.passed == b.total for b in buckets.values())
    arch = repo_architecture_gates()
    det = determinism_gate((_ROOT / "tests" / "fixtures" / "sample_flow.har").read_bytes(), config)

    checklist = [
        *arch,
        GateResult("No maps/noise in performance workload", corpus_ok, "see corpus buckets"),
        GateResult("One assertion per transaction / zero Thread-Group assertions", corpus_ok, ""),
        GateResult("Think time correctly scoped", corpus_ok, ""),
        GateResult("Correlations valid (producer+consumer+extractor)", corpus_ok, ""),
        GateResult("Parameters valid / CSV minimal / every CSV field used", corpus_ok, ""),
        GateResult("Every JMX variable resolvable", corpus_ok, ""),
        det,
        GateResult("REAL public-API corpus passes", buckets["REAL-public-API"].passed == buckets["REAL-public-API"].total,
                   f"{buckets['REAL-public-API'].passed}/{buckets['REAL-public-API'].total}"),
        GateResult("SYNTHETIC corpus passes",
                   buckets["SYNTHETIC-fixture"].passed == buckets["SYNTHETIC-fixture"].total
                   and buckets["SYNTHETIC-corpus"].passed == buckets["SYNTHETIC-corpus"].total,
                   f"fixture {buckets['SYNTHETIC-fixture'].passed}/{buckets['SYNTHETIC-fixture'].total}, "
                   f"corpus {buckets['SYNTHETIC-corpus'].passed}/{buckets['SYNTHETIC-corpus'].total}"),
    ]
    return checklist, buckets


if __name__ == "__main__":
    t0 = time.time()
    checklist, buckets = run_release_checklist()
    print("================ RELEASE CHECKLIST (measured) ================")
    for gr in checklist:
        print(f"[{'PASS' if gr.passed else 'FAIL'}] {gr.name}" + (f"   ({gr.detail})" if gr.detail else ""))
    print("\n---- corpus buckets (REAL vs SYNTHETIC kept separate) ----")
    for tag, b in buckets.items():
        print(f"  {tag:20} {b.passed}/{b.total} checks passed" + (f"  FAILURES: {b.failures[:5]}" if b.failures else ""))
    blockers = [gr.name for gr in checklist if not gr.passed]
    print(f"\nElapsed: {time.time()-t0:.1f}s")
    print("RELEASE =", "READY FOR CANDIDATE RELEASE" if not blockers else f"BLOCKED — blockers: {blockers}")
