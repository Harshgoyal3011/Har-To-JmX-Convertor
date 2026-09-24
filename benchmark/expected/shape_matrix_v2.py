"""Correlation ground truth + scorer for the FULL real corpus (APP01-APP26, 26 workflows).

Shape ids follow the expansion brief's 1-31 taxonomy (note: this renumbers the earlier 1-27 taxonomy;
SHAPES below is authoritative for this file).

Each expected correlation was hand-validated against the captured HAR by asking:
"would this value be required at runtime for the next request to address the correct resource/state?"
`policy` marks a dependency that is real but DELIBERATELY excluded by the agreed entity/catalog carve-out
- it is reported separately so it is never confused with an engine defect.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

BENCH = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BENCH.parent / "src"))

SHAPES = {
 1: "JSON -> URL path", 2: "JSON -> query param", 4: "JSON -> header", 6: "JSON -> full URL",
 7: "JSON -> path + suffix", 8: "nested JSON", 9: "array of objects", 10: "array of scalar STRINGS",
 11: "array of scalar NUMBERS", 12: "array -> HATEOAS link", 13: "numeric id", 14: "very short id",
 15: "UUID", 16: "JWT", 18: "opaque random string", 19: "embedded in consumer string",
 20: "producer/consumer names differ", 21: "GET producer", 22: "POST producer",
 24: "multiple consumers", 25: "multiple possible producers", 26: "reused after encoding",
 27: "resource id -> detail endpoint", 28: "search result -> selected entity",
 30: "create -> retrieve", 31: "one response -> multiple values",
}

JWT = ("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpZCI6MSwidXNlcm5hbWUiOiJlbWlseXMiLCJlbWFpbCI6ImVtaWx5"
       "LmpvaG5zb25AeC5kdW1teWpzb24uY29tIiwiaWF0IjoxNzkwMjI1MzI2LCJleHAiOjE3OTAyMjcxMjZ9."
       "Yp1FajaS-7kfMvhRlEtZFsie4p2xE6F7twlzPg8i3Co")

E: dict[str, dict] = {
 # ---------------- original 13 ----------------
 "app01_openlibrary_search_to_work": {"dom": "Library", "pm": "GET", "vt": "path-string",
   "c": [{"v": "/works/OL1904498W", "s": [1, 7, 9, 20, 21, 24, 27, 28], "cl": "path"}]},
 "app02_wikipedia_search_to_article": {"dom": "Knowledge/media", "pm": "GET", "vt": "numeric",
   "c": [{"v": "6615610", "s": [2, 8, 9, 13, 20, 21, 24, 28], "cl": "query"}]},
 "app03_pokeapi_list_to_detail": {"dom": "Media/gaming", "pm": "GET", "vt": "absolute-url",
   "c": [{"v": "https://pokeapi.co/api/v2/pokemon/1/", "s": [6, 9, 12, 21, 27], "cl": "url"}]},
 "app04_openfoodfacts_search_to_product": {"dom": "Retail/food", "pm": "GET", "vt": "string-id",
   "c": [{"v": "3168930010265", "s": [1, 9, 21, 27, 28], "cl": "path"}]},
 "app05_reqres_list_to_user": {"dom": "SaaS", "pm": "GET", "vt": "short-numeric",
   "c": [{"v": "3", "s": [1, 9, 13, 14, 21, 27], "cl": "path", "below": True}]},
 "app06_nominatim_search_to_details": {"dom": "Geo/logistics", "pm": "GET", "vt": "numeric",
   "c": [{"v": "275905280", "s": [2, 9, 13, 21, 28], "cl": "query", "policy": "entity-identifier carve-out"}]},
 "app07_dummyjson_login_to_me": {"dom": "SaaS/commerce", "pm": "POST", "vt": "jwt",
   "c": [{"v": JWT, "s": [4, 16, 20, 22], "cl": "header"}]},
 "app08_jsonplaceholder_create_to_comments": {"dom": "Generic web", "pm": "POST", "vt": "numeric",
   "c": [{"v": "101", "s": [1, 13, 22, 30], "cl": "path"}]},
 "app09_rickandmorty_episode_to_character": {"dom": "Media/entertainment", "pm": "GET", "vt": "absolute-url",
   "c": [{"v": "https://rickandmortyapi.com/api/character/1", "s": [6, 10, 12, 21], "cl": "url"}]},
 "app10_httpbin_uuid_to_query": {"dom": "Generic HTTP", "pm": "GET", "vt": "uuid",
   "c": [{"v": "31bcf27e-5e87-47c1-bb31-d9f6a1acf6b9", "s": [2, 15, 21], "cl": "query"}]},
 "app11_openmeteo_geocode_to_forecast": {"dom": "Geo/weather", "pm": "GET", "vt": "numeric",
   "c": [{"v": "53.33306", "s": [2, 8, 9, 21, 31], "cl": "query"},
         {"v": "-6.24889", "s": [2, 8, 9, 21, 31], "cl": "query"}]},
 "app12_nominatim_osmid_embedded": {"dom": "Geo/logistics", "pm": "GET", "vt": "numeric",
   "c": [{"v": "311466843", "s": [2, 13, 19, 21], "cl": "query-embedded"}]},
 "app13_restfulbooker_auth_create_read": {"dom": "Travel/booking", "pm": "POST", "vt": "numeric",
   "c": [{"v": "5454", "s": [1, 13, 22, 30], "cl": "path"}], "neg": ["817d15644a2398c"]},
 # ---------------- expansion 13 ----------------
 "app14_hackernews_topstories_to_item": {"dom": "Social/news", "pm": "GET", "vt": "numeric",
   "c": [{"v": "49823582", "s": [1, 11, 13, 21, 27], "cl": "path"}]},
 "app15_openalex_referenced_works": {"dom": "Education/research", "pm": "GET", "vt": "absolute-url",
   "c": [{"v": "https://openalex.org/W2069091362", "s": [1, 10, 19, 21], "cl": "path-derived"}]},
 "app16_postcodes_random_to_lookup": {"dom": "Logistics/geo", "pm": "GET", "vt": "string-with-space",
   "c": [{"v": "S13 7JT", "s": [1, 8, 21, 26], "cl": "path-encoded"}]},
 "app17_openbrewery_list_to_detail": {"dom": "Retail/hospitality", "pm": "GET", "vt": "uuid",
   "c": [{"v": "ae7b3174-8be8-4d53-a3a5-9b8240970eea", "s": [1, 9, 15, 21, 27], "cl": "path"}]},
 "app18_fhir_patient_search_to_read": {"dom": "Healthcare", "pm": "GET", "vt": "numeric",
   "c": [{"v": "4202", "s": [1, 8, 9, 13, 21, 27, 28], "cl": "path",
          "policy": "entity-identifier carve-out"}]},
 "app19_clinicaltrials_search_to_study": {"dom": "Government/clinical", "pm": "GET", "vt": "string-id",
   "c": [{"v": "NCT05604235", "s": [1, 8, 9, 21, 27, 28], "cl": "path"}]},
 "app20_gbif_species_search_to_names": {"dom": "Government/science", "pm": "GET", "vt": "numeric",
   "c": [{"v": "116892593", "s": [1, 8, 9, 13, 21, 25, 27], "cl": "path"}]},
 "app21_npm_search_to_package": {"dom": "Developer platform", "pm": "GET", "vt": "hyphenated-name",
   "c": [{"v": "performance-results-parser", "s": [1, 8, 9, 20, 21, 27, 28], "cl": "path"}]},
 "app22_crossref_works_to_doi": {"dom": "Education/publishing", "pm": "GET", "vt": "slash-bearing-id",
   "c": [{"v": "10.1002/9781119584414.ch4", "s": [1, 8, 9, 21, 27], "cl": "path-multisegment"}]},
 "app23_platzi_create_to_retrieve": {"dom": "E-commerce", "pm": "POST", "vt": "numeric",
   "c": [{"v": "428", "s": [1, 13, 22, 30], "cl": "path"}]},
 "app24_deckofcards_shuffle_draw_shuffle": {"dom": "Gaming/entertainment", "pm": "GET", "vt": "opaque",
   "c": [{"v": "hoe4kg03jrmq", "s": [1, 18, 21, 24], "cl": "path"}]},
 "app25_swapi_film_to_character": {"dom": "Media/entertainment", "pm": "GET", "vt": "absolute-url",
   "c": [{"v": "https://swapi.info/api/people/1", "s": [6, 10, 12, 21], "cl": "url"}]},
 "app26_opentdb_token_to_questions": {"dom": "Gaming/media", "pm": "GET", "vt": "opaque",
   "c": [{"v": "d23c01dff6f90c5e440739ca69c476173b42c9f52bcc1d02f837c61d140cc229",
          "s": [2, 18, 21], "cl": "query"}]},
}


def score() -> dict:
    from har2jmx.emit import build_jmx_xml
    from har2jmx.engine import analyze
    from har2jmx.lineage import build_lineage

    rows = []
    agg = {k: defaultdict(lambda: {"exp": 0, "det": 0}) for k in ("shape", "dom", "pm", "vt", "cl")}
    t = {"exp": 0, "det": 0, "false": 0, "below": 0, "policy": 0, "ver": 0, "mat": 0}

    for stem, gt in E.items():
        har = BENCH / "normalized" / f"{stem}.har"
        if not har.exists():
            continue
        res = analyze(har.read_bytes())
        xml = build_jmx_xml(res).decode()
        lin = build_lineage(res.capture)
        ok = {c.value for c in res.extractor_checks if c.ok}
        got = {str(c.value) for c in res.correlations if c.consumers}
        exp_vals = set()

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
            if hit:
                dec = next(c for c in res.correlations if str(c.value) == v)
                t["ver"] += int(v in ok)
                t["mat"] += int(("${%s}" % dec.variable) in xml and v not in xml)
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
                if e.get("policy"):
                    stage, cause = "POLICY", e["policy"]
                elif e.get("below"):
                    stage, cause = "DISCOVERY", "below the documented short-value floor"
                elif f is None or not f.producers:
                    stage, cause = "DISCOVERY", "value never emitted as a producer"
                elif not f.consumers:
                    stage, cause = "DISCOVERY", "producer found, consumer slot never matched"
                elif d is None:
                    stage, cause = "DISCOVERY", "dropped before classification"
                elif d.classification.value != "RUNTIME_GENERATED":
                    stage, cause = "CLASSIFICATION", f"{d.classification.value} (is_id={d.is_identifier})"
                elif v not in ok:
                    stage, cause = "VALIDATION", "extractor did not verify"
                else:
                    stage, cause = "SUBSTITUTION", "decided+verified but not substituted"
            rows.append({"har": stem, "dom": gt["dom"], "v": v[:46], "shapes": e["s"],
                         "pm": gt["pm"], "vt": gt["vt"], "cl": e["cl"], "hit": hit,
                         "stage": stage, "cause": cause})

        for bad in gt.get("neg", []):
            if bad in got:
                t["false"] += 1
                rows.append({"har": stem, "v": bad, "FALSE": True})
        t["false"] += len(got - exp_vals - set(gt.get("neg", [])))

    def p(d):
        return round(d["det"] / d["exp"], 3) if d["exp"] else None
    real_exp = t["exp"] - t["below"] - t["policy"]
    return {
      "summary": {
        "workflows": len(E), "expected": t["exp"], "detected": t["det"],
        "missed": t["exp"] - t["det"], "missed_policy_excluded": t["policy"],
        "missed_below_threshold": t["below"],
        "missed_engine_gaps": t["exp"] - t["det"] - t["policy"] - t["below"],
        "false_correlations": t["false"],
        "recall": round(t["det"] / t["exp"], 3) if t["exp"] else None,
        "recall_excl_policy_and_threshold": round(t["det"] / real_exp, 3) if real_exp else None,
        "precision": round(t["det"] / (t["det"] + t["false"]), 3) if (t["det"] + t["false"]) else None,
        "verified_extractor_rate": round(t["ver"] / t["det"], 3) if t["det"] else None,
        "materialization_rate": round(t["mat"] / t["det"], 3) if t["det"] else None,
      },
      "by_shape": {f"{k:2d} {SHAPES.get(k, '?')}": {**v, "recall": p(v)}
                   for k, v in sorted(agg["shape"].items())},
      "by_domain": {k: {**v, "recall": p(v)} for k, v in sorted(agg["dom"].items())},
      "by_producer_method": {k: {**v, "recall": p(v)} for k, v in sorted(agg["pm"].items())},
      "by_value_type": {k: {**v, "recall": p(v)} for k, v in sorted(agg["vt"].items())},
      "by_consumer_location": {k: {**v, "recall": p(v)} for k, v in sorted(agg["cl"].items())},
      "rows": rows,
    }


if __name__ == "__main__":
    o = score()
    (BENCH / "SHAPE_MATRIX_V2.json").write_text(json.dumps(o, indent=1), encoding="utf-8")
    print(json.dumps(o["summary"], indent=1))
    print("\nSHAPES WITH A GAP (recall < 1):")
    for k, v in o["by_shape"].items():
        if v["recall"] is not None and v["recall"] < 1:
            print(f"  {k:36} {v['det']}/{v['exp']}  {v['recall']}")
    print("\nBY PRODUCER METHOD:")
    for k, v in o["by_producer_method"].items():
        print(f"  {k:6} {v['det']}/{v['exp']}  {v['recall']}")
    print("\nBY CONSUMER LOCATION:")
    for k, v in o["by_consumer_location"].items():
        print(f"  {k:20} {v['det']}/{v['exp']}  {v['recall']}")
    print("\nMISSES:")
    for r in o["rows"]:
        if r.get("FALSE"):
            print(f"  FALSE {r['har']}: {r['v']}")
        elif not r["hit"]:
            print(f"  {r['stage']:15} {r['har'][:38]:38} {r['v'][:34]:34} {r['cause']}")
