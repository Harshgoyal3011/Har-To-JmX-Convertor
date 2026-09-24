"""Correlation-shape ground truth + scorer for the whole real corpus (APP01-APP13).

Each expected correlation is hand-validated against the captured HAR by asking the PE question:
"would this value be required at runtime for the next request to address the correct resource/state?"

Shape ids follow the brief's 1-27 taxonomy. Breakdowns are produced by shape, domain, producer HTTP
method, value type and consumer location, so the output says WHICH KINDS of correlation the engine
cannot generalize to - not merely how many it missed.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

BENCH = Path(__file__).resolve().parents[1]
ROOT = BENCH.parent
sys.path.insert(0, str(ROOT / "src"))

# har stem -> expected correlations. "neg" lists server values that must NOT be correlated.
EXPECTED: dict[str, dict] = {
 "app01_openlibrary_search_to_work": {"domain": "Library", "producer": "GET", "vtype": "path-string",
   "corr": [{"v": "/works/OL1904498W", "shapes": [1, 7, 8, 17, 20, 24], "cloc": "path"}]},
 "app02_wikipedia_search_to_article": {"domain": "Knowledge/media", "producer": "GET", "vtype": "numeric",
   "corr": [{"v": "6615610", "shapes": [2, 8, 11, 17, 20], "cloc": "query"}]},
 "app03_pokeapi_list_to_detail": {"domain": "Media/gaming", "producer": "GET", "vtype": "absolute-url",
   "corr": [{"v": "https://pokeapi.co/api/v2/pokemon/1/", "shapes": [6, 10, 17, 24], "cloc": "url"}]},
 "app04_openfoodfacts_search_to_product": {"domain": "Retail/food", "producer": "GET", "vtype": "string-id",
   "corr": [{"v": "3168930010265", "shapes": [1, 8, 10, 17, 25], "cloc": "path"}]},
 "app05_reqres_list_to_user": {"domain": "SaaS", "producer": "GET", "vtype": "short-numeric",
   "corr": [{"v": "3", "shapes": [1, 12, 17], "cloc": "path", "below_threshold": True}]},
 "app06_nominatim_search_to_details": {"domain": "Geo/logistics", "producer": "GET", "vtype": "numeric",
   "corr": [{"v": "275905280", "shapes": [2, 11, 17], "cloc": "query"}]},
 "app07_dummyjson_login_to_me": {"domain": "SaaS/commerce", "producer": "POST", "vtype": "jwt",
   "corr": [{"v": "__JWT__", "shapes": [4, 8, 14, 18], "cloc": "header"}]},
 "app08_jsonplaceholder_create_to_comments": {"domain": "Generic web", "producer": "POST", "vtype": "numeric",
   "corr": [{"v": "101", "shapes": [1, 11, 18, 25], "cloc": "path"}]},
 "app09_rickandmorty_episode_to_character": {"domain": "Media/entertainment", "producer": "GET",
   "vtype": "absolute-url",
   "corr": [{"v": "https://rickandmortyapi.com/api/character/1", "shapes": [6, 10, 24], "cloc": "url"}]},
 "app10_httpbin_uuid_to_query": {"domain": "Generic HTTP", "producer": "GET", "vtype": "uuid",
   "corr": [{"v": "31bcf27e-5e87-47c1-bb31-d9f6a1acf6b9", "shapes": [2, 13], "cloc": "query"}]},
 "app11_openmeteo_geocode_to_forecast": {"domain": "Geo/weather", "producer": "GET", "vtype": "numeric",
   "corr": [{"v": "53.33306", "shapes": [2, 9, 20], "cloc": "query"},
            {"v": "-6.24889", "shapes": [2, 9, 20], "cloc": "query"}]},
 "app12_nominatim_osmid_embedded": {"domain": "Geo/logistics", "producer": "GET", "vtype": "numeric",
   "corr": [{"v": "311466843", "shapes": [2, 23], "cloc": "query-embedded"}]},
 "app13_restfulbooker_auth_create_read": {"domain": "Travel/booking", "producer": "POST", "vtype": "numeric",
   "corr": [{"v": "5454", "shapes": [1, 11, 18, 25, 27], "cloc": "path"}],
   # the opaque auth token IS server-generated but NOTHING downstream consumes it in this capture,
   # so correlating it would be a false positive. Recorded as a true negative.
   "neg": ["817d15644a2398c"]},
}

JWT = ("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpZCI6MSwidXNlcm5hbWUiOiJlbWlseXMiLCJlbWFpbCI6ImVtaWx5"
       "LmpvaG5zb25AeC5kdW1teWpzb24uY29tIiwiaWF0IjoxNzkwMjI1MzI2LCJleHAiOjE3OTAyMjcxMjZ9."
       "Yp1FajaS-7kfMvhRlEtZFsie4p2xE6F7twlzPg8i3Co")

SHAPE_NAMES = {
 1: "response JSON -> URL path", 2: "response JSON -> query param", 4: "response JSON -> request header",
 6: "response JSON -> complete downstream URL", 7: "path -> path segment + suffix",
 8: "producer/consumer field names differ", 9: "nested JSON -> downstream",
 10: "array element -> downstream", 11: "numeric generated id", 12: "short generated id",
 13: "UUID", 14: "JWT-like token", 17: "GET/search producer", 18: "POST/create producer",
 20: "one producer -> multiple consumers", 23: "value embedded in larger string",
 24: "HATEOAS hyperlink -> request", 25: "generated id -> detail request",
 27: "generated business entity id -> later operation",
}


def score() -> dict:
    from har2jmx.emit import build_jmx_xml
    from har2jmx.engine import analyze
    from har2jmx.lineage import build_lineage

    rows, by_shape = [], defaultdict(lambda: {"exp": 0, "det": 0})
    by_dom, by_method, by_vtype, by_cloc = (defaultdict(lambda: {"exp": 0, "det": 0}) for _ in range(4))
    tot = {"exp": 0, "det": 0, "false": 0, "below": 0, "materialized": 0, "verified": 0}

    for stem, gt in EXPECTED.items():
        har = BENCH / "normalized" / f"{stem}.har"
        if not har.exists():
            continue
        res = analyze(har.read_bytes())
        xml = build_jmx_xml(res).decode()
        lin = build_lineage(res.capture)
        ok = {c.value for c in res.extractor_checks if c.ok}
        got = {str(c.value) for c in res.correlations if c.consumers}
        expected_vals = set()

        for e in gt["corr"]:
            v = JWT if e["v"] == "__JWT__" else e["v"]
            expected_vals.add(v)
            hit = v in got
            tot["exp"] += 1
            tot["det"] += int(hit)
            tot["below"] += int(bool(e.get("below_threshold")) and not hit)
            if hit:
                dec = next(c for c in res.correlations if str(c.value) == v)
                if v in ok:
                    tot["verified"] += 1
                if ("${%s}" % dec.variable) in xml and v not in xml:
                    tot["materialized"] += 1
            for sh in e["shapes"]:
                by_shape[sh]["exp"] += 1
                by_shape[sh]["det"] += int(hit)
            for bucket, key in ((by_dom, gt["domain"]), (by_method, gt["producer"]),
                                (by_vtype, gt["vtype"]), (by_cloc, e["cloc"])):
                bucket[key]["exp"] += 1
                bucket[key]["det"] += int(hit)

            stage = ""
            if not hit:
                f = lin.by_value(v)
                verdict = res.classification.by_value(v)
                if f is None or not f.producers:
                    stage = "DISCOVERY (value never emitted as a producer)"
                elif not f.consumers:
                    stage = "DISCOVERY (producer found, consumer slot never matched)"
                elif verdict is None:
                    stage = "DISCOVERY (dropped before classification)"
                elif verdict.classification.value != "RUNTIME_GENERATED":
                    stage = f"CLASSIFICATION ({verdict.classification.value})"
                elif v not in ok:
                    stage = "VALIDATION (extractor did not verify)"
                else:
                    stage = "SUBSTITUTION"
            rows.append({"har": stem, "domain": gt["domain"], "value": v[:44],
                         "shapes": e["shapes"], "producer": gt["producer"], "vtype": gt["vtype"],
                         "consumer_location": e["cloc"], "detected": hit, "failure_stage": stage})

        for bad in gt.get("neg", []):
            if bad in got:
                tot["false"] += 1
                rows.append({"har": stem, "value": bad, "FALSE_CORRELATION": True})
        tot["false"] += len(got - expected_vals - set(gt.get("neg", [])))

    def pct(d):
        return round(d["det"] / d["exp"], 3) if d["exp"] else None

    return {
      "summary": {
        "workflows": len(EXPECTED), "expected": tot["exp"], "detected": tot["det"],
        "missed": tot["exp"] - tot["det"], "missed_below_threshold": tot["below"],
        "false_correlations": tot["false"],
        "recall": round(tot["det"] / tot["exp"], 3) if tot["exp"] else None,
        "recall_excl_below_threshold": round(tot["det"] / (tot["exp"] - tot["below"]), 3)
            if (tot["exp"] - tot["below"]) else None,
        "precision": round(tot["det"] / (tot["det"] + tot["false"]), 3)
            if (tot["det"] + tot["false"]) else None,
        "verified_extractor_rate": round(tot["verified"] / tot["det"], 3) if tot["det"] else None,
        "materialization_rate": round(tot["materialized"] / tot["det"], 3) if tot["det"] else None,
      },
      "by_shape": {f"{k} {SHAPE_NAMES.get(k, '?')}": {**v, "recall": pct(v)}
                   for k, v in sorted(by_shape.items())},
      "by_domain": {k: {**v, "recall": pct(v)} for k, v in sorted(by_dom.items())},
      "by_producer_method": {k: {**v, "recall": pct(v)} for k, v in sorted(by_method.items())},
      "by_value_type": {k: {**v, "recall": pct(v)} for k, v in sorted(by_vtype.items())},
      "by_consumer_location": {k: {**v, "recall": pct(v)} for k, v in sorted(by_cloc.items())},
      "rows": rows,
    }


if __name__ == "__main__":
    out = score()
    (BENCH / "SHAPE_MATRIX.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps(out["summary"], indent=1))
    print("\nBY SHAPE (recall):")
    for k, v in out["by_shape"].items():
        flag = "  <== GAP" if v["recall"] == 0 else ""
        print(f"  {k:48} {v['det']}/{v['exp']}  {v['recall']}{flag}")
    print("\nBY PRODUCER METHOD / VALUE TYPE / CONSUMER LOCATION:")
    for name, b in (("method", out["by_producer_method"]), ("vtype", out["by_value_type"]),
                    ("cloc", out["by_consumer_location"])):
        for k, v in b.items():
            print(f"  {name:7} {k:18} {v['det']}/{v['exp']}  {v['recall']}")
    print("\nFAILURES:")
    for r in out["rows"]:
        if r.get("FALSE_CORRELATION"):
            print(f"  FALSE  {r['har']}: {r['value']}")
        elif not r["detected"]:
            print(f"  MISS   {r['har'][:40]:40} {r['value'][:38]:38} -> {r['failure_stage']}")
