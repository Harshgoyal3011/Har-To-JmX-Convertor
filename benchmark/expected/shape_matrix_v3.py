"""FINAL ground truth + scorer for the whole REAL corpus (APP01-APP44, 44 workflows).

Extends shape_matrix_v2 (APP01-26) with the 3 authentication workflows (APP27-29) and the second
expansion (APP30-44). The SYNTHETIC_MFA fixture is deliberately NOT here - it is scored separately and
excluded from every real-application figure.

Per expected correlation:
  policy=...    a real dependency intentionally left to parameterization by the agreed entity/catalog
                carve-out - reported separately, never counted as an engine defect
  below=True    below the documented short-value floor
  secondary=True a genuine additional dependency in the same journey (a sibling field that is also
                produced and consumed); counted so precision is not penalised for a correct detection
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

BENCH = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BENCH.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from shape_matrix_v2 import E as E_CORE, SHAPES  # noqa: E402

PZ_ACCESS = ("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOjEsImlhdCI6MTc5MDIyODQxOSwiZXhwIjoxNzkxOTU2"
             "NDE5fQ.cWIU6d-5MADfM9esdKDtHHEJr0ni4h222HjirBmsfpE")
PZ_REFRESH = ("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOjEsImlhdCI6MTc5MDIyODQxOSwiZXhwIjoxNzkwMjY0"
              "NDE5fQ.vAuQ4ysR3EgWQ7Opo8cNW_bHbM4MN-fQYJMW9ovaXf4")
_H = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
_B = ("eyJpZCI6MSwidXNlcm5hbWUiOiJlbWlseXMiLCJlbWFpbCI6ImVtaWx5LmpvaG5zb25AeC5kdW1teWpzb24uY29tIiwi"
      "Zmlyc3ROYW1lIjoiRW1pbHkiLCJsYXN0TmFtZSI6IkpvaG5zb24iLCJnZW5kZXIiOiJmZW1hbGUiLCJpbWFnZSI6Imh0"
      "dHBzOi8vZHVtbXlqc29uLmNvbS9pY29uL2VtaWx5cy8xMjgiLCJpYXQiOjE3OTAyMjg0M")
DJ_A1 = _H + _B + "jAsImV4cCI6MTc5MDIzMDIyMH0.7MesqdjENv4iY7_rCi8tEdXcgbFaIx7hoHh17IcMp7Q"
DJ_R1 = _H + _B + "jAsImV4cCI6MTc5MjgyMDQyMH0.JbxreBnwb5HqOpxnfW7eOt5gm6jCdMsvgAbuiwC6WV0"
DJ_A2 = _H + _B + "jEsImV4cCI6MTc5MDIzMDIyMX0.Mnm-PzzY3prtVGegZXlgpww8u_FW8lHCj8xfJroAskQ"

E_NEW: dict[str, dict] = {
 "app27_quotes_csrf_form_login": {"dom": "Auth sandbox", "pm": "GET", "vt": "opaque", "auth": True,
   "c": [{"v": "dVacEpRxvlUBjTtGKOJhqmbkIgDysQWYHorLZNzwMeiuXAfnPSCF", "s": [18, 20, 21], "cl": "body"}]},
 "app28_platzi_email_login_to_profile": {"dom": "E-commerce / SaaS", "pm": "POST", "vt": "jwt", "auth": True,
   "c": [{"v": PZ_ACCESS, "s": [4, 16, 20, 22], "cl": "header"}], "neg": [PZ_REFRESH]},
 "app29_dummyjson_refresh_token_chain": {"dom": "SaaS / commerce", "pm": "POST", "vt": "jwt", "auth": True,
   "c": [{"v": DJ_R1, "s": [16, 22], "cl": "body"}, {"v": DJ_A2, "s": [4, 16, 22], "cl": "header"}],
   "neg": [DJ_A1]},
 "app30_restfulbooker_create_update_retrieve": {"dom": "Travel / booking", "pm": "POST", "vt": "numeric",
   "c": [{"v": "4248", "s": [1, 13, 22, 24, 30], "cl": "path"}], "neg": ["ffb48ff29777745"]},
 "app31_huggingface_models": {"dom": "GenAI / AI", "pm": "GET", "vt": "slash-bearing-id",
   "c": [{"v": "sentence-transformers/all-MiniLM-L6-v2", "s": [1, 21, 27], "cl": "path-multisegment"},
         {"v": "sentence-transformers", "s": [1, 21], "cl": "path", "secondary": True}]},
 "app32_huggingface_datasets": {"dom": "GenAI / AI", "pm": "GET", "vt": "slash-bearing-id",
   "c": [{"v": "m-a-p/FineFineWeb", "s": [1, 21, 27], "cl": "path-multisegment"},
         {"v": "m-a-p", "s": [1, 21], "cl": "path", "secondary": True}]},
 "app33_frankfurter_rate_date": {"dom": "Finance / FX", "pm": "GET", "vt": "date",
   "c": [{"v": "2026-09-23", "s": [1, 21, 27], "cl": "path"}]},
 "app34_wikidata_search_to_entity": {"dom": "Knowledge graph", "pm": "GET", "vt": "coded-id",
   "c": [{"v": "Q1761", "s": [2, 9, 21, 28], "cl": "query", "policy": "entity-identifier carve-out"}]},
 "app35_dummyjson_product_search": {"dom": "E-commerce", "pm": "GET", "vt": "numeric",
   "c": [{"v": "101", "s": [1, 9, 13, 21, 28], "cl": "path", "policy": "entity-identifier carve-out"}]},
 "app36_diseasesh_country_iso3": {"dom": "Healthcare data", "pm": "GET", "vt": "short-code",
   "c": [{"v": "IRL", "s": [1, 8, 21, 27], "cl": "path"}]},
 "app37_artic_artwork_search": {"dom": "Culture / museum", "pm": "GET", "vt": "numeric",
   "c": [{"v": "656", "s": [1, 9, 13, 21, 28], "cl": "path", "policy": "entity-identifier carve-out"}]},
 "app38_github_tag_to_ref": {"dom": "Developer platform", "pm": "GET", "vt": "version-tag",
   "c": [{"v": "v5.6.3-rc2", "s": [1, 9, 21, 27], "cl": "path"}]},
 "app39_tvmaze_show_to_seasons": {"dom": "Media / TV", "pm": "GET", "vt": "numeric",
   "c": [{"v": "139", "s": [1, 13, 21, 27], "cl": "path", "policy": "entity-identifier carve-out"}]},
 "app40_cratesio_search_to_crate": {"dom": "Developer platform", "pm": "GET", "vt": "name",
   "c": [{"v": "hashbrown", "s": [1, 9, 20, 21, 28], "cl": "path",
          "policy": "entity-identifier carve-out"}]},
 "app41_openverse_image_search": {"dom": "Media / CC images", "pm": "GET", "vt": "uuid",
   # detail_url is a SECOND genuine dependency: the search response carries the exact URL of the next
   # request (the HATEOAS shape). It was missing from the original ground truth only because the whole
   # workflow was being dropped as noise, so it was never observable. Added on the same standard
   # already applied to the Hugging Face sibling fields.
   "c": [{"v": "1c5442f6-6bb6-4ab7-b603-f598e7579dd2", "s": [1, 9, 15, 21, 27], "cl": "path"},
         {"v": "https://api.openverse.org/v1/images/1c5442f6-6bb6-4ab7-b603-f598e7579dd2/",
          "s": [6, 9, 12, 21], "cl": "url", "secondary": True}]},
 "app42_dummyjson_put_producer": {"dom": "E-commerce", "pm": "PUT", "vt": "short-numeric",
   "c": [{"v": "78", "s": [1, 13, 14, 23, 25], "cl": "path", "below": True}]},
 "app43_ukpolice_forces": {"dom": "Government / policing", "pm": "GET", "vt": "slug",
   "c": [{"v": "avon-and-somerset", "s": [1, 9, 20, 21, 28], "cl": "path",
          "policy": "entity-identifier carve-out"}]},
 "app44_cocktaildb_random_lookup": {"dom": "Food & beverage", "pm": "GET", "vt": "numeric",
   "c": [{"v": "13020", "s": [2, 9, 13, 21, 27], "cl": "query"}]},
}

E = {**E_CORE, **E_NEW}


def score() -> dict:
    from har2jmx.emit import build_jmx_xml, validate_plan
    from har2jmx.engine import analyze
    from har2jmx.lineage import build_lineage
    from har2jmx.validate import MaterializationStatus, audit_materialization

    rows = []
    agg = {k: defaultdict(lambda: {"exp": 0, "det": 0}) for k in ("shape", "dom", "pm", "vt", "cl")}
    t = {"exp": 0, "det": 0, "false": 0, "below": 0, "policy": 0, "ver": 0, "mat": 0,
         "noise_lost": 0, "plan_problems": 0, "csv": 0}
    auth = {"apps": 0, "corr_exp": 0, "corr_det": 0, "cred_ok": 0}

    for stem, gt in E.items():
        har = BENCH / "normalized" / f"{stem}.har"
        if not har.exists():
            continue
        res = analyze(har.read_bytes())
        xml = build_jmx_xml(res).decode()
        lin = build_lineage(res.capture)
        ok = {c.value for c in res.extractor_checks if c.ok}
        matz = {c.variable: c.status for c in audit_materialization(res, xml)}
        got = {str(c.value) for c in res.correlations if c.consumers}
        probs = validate_plan(res, xml)
        t["plan_problems"] += len(probs)
        cols = [cc.name for d in res.parameterization.datasets for cc in d.columns]
        t["csv"] += len(cols)
        exp_vals = set()
        if gt.get("auth"):
            auth["apps"] += 1

        for e in gt["c"]:
            v = e["v"]
            exp_vals.add(v)
            hit = v in got
            t["exp"] += 1
            t["det"] += int(hit)
            if not hit and e.get("below"):
                t["below"] += 1
            if not hit and e.get("policy"):
                t["policy"] += 1
            if gt.get("auth"):
                auth["corr_exp"] += 1
                auth["corr_det"] += int(hit)
            if hit:
                dec = next(c for c in res.correlations if str(c.value) == v)
                t["ver"] += int(v in ok)
                t["mat"] += int(matz.get(dec.variable) == MaterializationStatus.MATERIALIZED)
            for sh in e["s"]:
                agg["shape"][sh]["exp"] += 1
                agg["shape"][sh]["det"] += int(hit)
            for key, val in (("dom", gt["dom"]), ("pm", gt["pm"]), ("vt", gt["vt"]), ("cl", e["cl"])):
                agg[key][val]["exp"] += 1
                agg[key][val]["det"] += int(hit)

            stage, cause = "", ""
            if not hit:
                f = lin.by_value(v)
                d = res.classification.by_value(v)
                excluded_all = all(q.classification.excluded for q in res.capture.requests)
                if e.get("policy"):
                    stage, cause = "POLICY", e["policy"]
                elif e.get("below"):
                    stage, cause = "FLOOR", "below the documented short-value floor"
                elif excluded_all:
                    stage, cause = "NOISE", "entire workflow excluded as noise; JMX has no samplers"
                    t["noise_lost"] += 1
                elif f is None or not f.producers:
                    stage, cause = "DISCOVERY", "value never emitted as a producer"
                elif not f.consumers:
                    stage, cause = "DISCOVERY", "producer found, consumer slot never matched"
                elif d is None:
                    stage, cause = "DISCOVERY", "dropped before classification"
                elif d.classification.value != "RUNTIME_GENERATED":
                    stage, cause = "CLASSIFICATION", f"{d.classification.value} is_id={d.is_identifier}"
                elif v not in ok:
                    stage, cause = "VALIDATION", "extractor did not verify"
                else:
                    stage, cause = "SUBSTITUTION", "verified but not substituted"
            rows.append({"har": stem, "dom": gt["dom"], "v": v[:44], "shapes": e["s"], "pm": gt["pm"],
                         "vt": gt["vt"], "cl": e["cl"], "hit": hit, "secondary": e.get("secondary", False),
                         "stage": stage, "cause": cause, "csv": cols, "plan_problems": probs})

        for bad in gt.get("neg", []):
            if bad in got:
                t["false"] += 1
                rows.append({"har": stem, "v": bad[:44], "FALSE": True,
                             "cause": "must NOT correlate (unused/superseded/user input)"})
        t["false"] += len(got - exp_vals - set(gt.get("neg", [])))

    def p(d):
        return round(d["det"] / d["exp"], 3) if d["exp"] else None
    real = t["exp"] - t["below"] - t["policy"]
    return {
      "summary": {
        "real_workflows": len(E), "expected": t["exp"], "detected": t["det"],
        "missed_total": t["exp"] - t["det"],
        "missed_policy": t["policy"], "missed_floor": t["below"],
        "missed_engine_gaps": t["exp"] - t["det"] - t["policy"] - t["below"],
        "false_correlations": t["false"],
        "recall": round(t["det"] / t["exp"], 3) if t["exp"] else None,
        "recall_excl_policy_and_floor": round(t["det"] / real, 3) if real else None,
        "precision": round(t["det"] / (t["det"] + t["false"]), 3) if (t["det"] + t["false"]) else None,
        "verified_extractor_rate": round(t["ver"] / t["det"], 3) if t["det"] else None,
        "materialization_rate": round(t["mat"] / t["det"], 3) if t["det"] else None,
        "workflows_lost_to_noise": t["noise_lost"], "plan_problems": t["plan_problems"],
        "total_csv_columns": t["csv"],
      },
      "authentication": {**auth,
        "auth_correlation_recall": round(auth["corr_det"] / auth["corr_exp"], 3) if auth["corr_exp"] else None},
      "by_shape": {f"{k:2d} {SHAPES.get(k,'?')}": {**v, "recall": p(v)} for k, v in sorted(agg["shape"].items())},
      "by_domain": {k: {**v, "recall": p(v)} for k, v in sorted(agg["dom"].items())},
      "by_producer_method": {k: {**v, "recall": p(v)} for k, v in sorted(agg["pm"].items())},
      "by_value_type": {k: {**v, "recall": p(v)} for k, v in sorted(agg["vt"].items())},
      "by_consumer_location": {k: {**v, "recall": p(v)} for k, v in sorted(agg["cl"].items())},
      "rows": rows,
    }


if __name__ == "__main__":
    o = score()
    (BENCH / "SHAPE_MATRIX_V3.json").write_text(json.dumps(o, indent=1), encoding="utf-8")
    print(json.dumps(o["summary"], indent=1))
    print("\nAUTHENTICATION:", json.dumps(o["authentication"]))
    print("\nBY PRODUCER METHOD:")
    for k, v in o["by_producer_method"].items():
        print(f"  {k:6} {v['det']}/{v['exp']}  {v['recall']}")
    print("\nMISSES BY STAGE:")
    by_stage = defaultdict(list)
    for r in o["rows"]:
        if r.get("FALSE"):
            by_stage["FALSE"].append(r)
        elif not r["hit"]:
            by_stage[r["stage"]].append(r)
    for st in sorted(by_stage):
        print(f"  {st} ({len(by_stage[st])}):")
        for r in by_stage[st]:
            print(f"     {r['har'][:38]:38} {r['v'][:34]:34} {r['cause'][:52]}")
