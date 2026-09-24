"""Hand-labelled ground truth for the REAL captured applications, + the scorer.

Labelling rule (stated so it can be audited, not just asserted):

  A value is an EXPECTED CORRELATION when the recorded journey proves the server produced it and a
  LATER request depends on that exact value. In a search -> detail journey the detail request must use
  the id the search actually returned; if it does not, the generated script no longer exercises the
  real dependency and breaks as soon as the backing dataset changes. Correlating it is therefore the
  correct primary answer, and varying the SCENARIO is done by parameterising the SEARCH INPUT.

  A value is an EXPECTED PARAMETER when a performance engineer would intentionally vary it between
  virtual users (the search term, the filter) — not the server's answer to that search.

Ground truth was read off the captured HAR bodies, never from the converter's output.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

BENCH = Path(__file__).resolve().parents[1]
ROOT = BENCH.parent
sys.path.insert(0, str(ROOT / "src"))

GT: dict[str, dict] = {
    "app01_openlibrary_search_to_work": {
        "application": "OpenLibrary", "domain": "Library / public catalogue",
        "expected_correlations": [
            {"value": "/works/OL1904498W", "producer": "GET /search.json -> docs[0].key",
             "consumers": ["GET /works/OL1904498W.json", "GET /works/OL1904498W/editions.json"],
             "shape": "path-style resource key returned in JSON, reused as URL path + extension"}],
        "expected_parameters": ["q"],
        "expected_noise_hosts": ["covers.openlibrary.org", "apollo.archive.org", "archive.org",
                                 "sink.archive.org", "athena.archive.org"],
        "notes": "apollo.archive.org/matomo.php is a Matomo analytics beacon; sink.archive.org is Sentry.",
    },
    "app02_wikipedia_search_to_article": {
        "application": "Wikipedia", "domain": "Knowledge / media",
        "expected_correlations": [
            {"value": "6615610", "producer": "GET api.php?list=search -> query.search[0].pageid",
             "consumers": ["GET api.php?pageids=6615610&prop=info|categories",
                           "GET api.php?pageids=6615610&prop=extracts"],
             "shape": "numeric id returned in JSON, reused as a query parameter"}],
        "expected_parameters": ["srsearch"],
        "expected_noise_hosts": ["upload.wikimedia.org"],
        "notes": "en.wikipedia.org/ins-502b/v2/events is a FIRST-PARTY EventLogging beacon (same host "
                 "as the business API), so host-based filtering cannot separate it.",
    },
    "app03_pokeapi_list_to_detail": {
        "application": "PokeAPI", "domain": "Media / gaming catalogue",
        "expected_correlations": [
            {"value": "https://pokeapi.co/api/v2/pokemon/1/",
             "producer": "GET /api/v2/pokemon?limit=2 -> results[0].url",
             "consumers": ["GET https://pokeapi.co/api/v2/pokemon/1/"],
             "shape": "ABSOLUTE URL returned in JSON, reused verbatim as the next request URL"}],
        "expected_parameters": [],
        "expected_noise_hosts": [],
        "notes": "limit/offset are fixed request configuration and should stay hardcoded.",
    },
    "app04_openfoodfacts_search_to_product": {
        "application": "OpenFoodFacts", "domain": "Retail / food",
        "expected_correlations": [
            {"value": "3168930010265", "producer": "GET /api/v2/search -> products[0].code",
             "consumers": ["GET /api/v2/product/3168930010265"],
             "shape": "string id returned in JSON, reused as a URL path segment"}],
        "expected_parameters": ["categories_tags_en"],
        "expected_noise_hosts": [],
        "notes": "the category filter is the scenario input; the product code is the server's answer.",
    },
    "app05_reqres_list_to_user": {
        "application": "reqres.in", "domain": "SaaS / demo REST service",
        "expected_correlations": [
            {"value": "3", "producer": "GET /api/users?page=2 -> data[0].id",
             "consumers": ["GET /api/users/3"],
             "shape": "SMALL numeric id reused as a URL path segment",
             "below_documented_threshold": True}],
        "expected_parameters": [],
        "expected_noise_hosts": [],
        "notes": "the id is a single digit, below the converter's documented <3-char correlatable "
                 "minimum. Counted separately so the tool is judged fairly on its stated contract.",
    },
    "app06_nominatim_search_to_details": {
        "application": "Nominatim (OpenStreetMap)", "domain": "Geo / logistics",
        "expected_correlations": [
            {"value": "275905280", "producer": "GET /search?q=Dublin -> [0].place_id",
             "consumers": ["GET /details?place_id=275905280"],
             "shape": "numeric id returned in a JSON ARRAY root, reused as a query parameter"}],
        "expected_parameters": ["q"],
        "expected_noise_hosts": [],
        "notes": "q=Dublin is the scenario input; place_id is the server's answer to it.",
    },
}


def score() -> dict:
    from har2jmx.engine import analyze

    rows, tot_exp, tot_det, tot_false, tot_below = [], 0, 0, 0, 0
    for stem, gt in GT.items():
        har = BENCH / "normalized" / f"{stem}.har"
        if not har.exists():
            continue
        res = analyze(har.read_bytes())
        got_vals = {str(c.value) for c in res.correlations if c.consumers}
        csv_cols = {c.name for d in res.parameterization.datasets for c in d.columns}

        exp = gt["expected_correlations"]
        hit = [e for e in exp if str(e["value"]) in got_vals]
        miss = [e for e in exp if str(e["value"]) not in got_vals]
        below = [e for e in miss if e.get("below_documented_threshold")]
        expected_vals = {str(e["value"]) for e in exp}
        false_corr = sorted(got_vals - expected_vals)

        # a dependent value that became a CSV column instead of a correlation = actively wrong
        miscast = [e for e in miss
                   if any(str(e["value"]) == str(r.get(c, "")) for d in res.parameterization.datasets
                          for r in d.rows for c in (cc.name for cc in d.columns))]

        exp_params = set(gt["expected_parameters"])
        rows.append({
            "har": stem, "application": gt["application"], "domain": gt["domain"],
            "expected_correlations": len(exp), "detected_correlations": len(hit),
            "missed_correlations": len(miss), "missed_below_threshold": len(below),
            "false_correlations": len(false_corr), "false_correlation_values": false_corr,
            "miscast_as_parameter": [str(e["value"]) for e in miscast],
            "recall": round(len(hit) / len(exp), 3) if exp else None,
            "precision": round(len(hit) / len(got_vals), 3) if got_vals else None,
            "expected_parameters": sorted(exp_params),
            "detected_csv_columns": sorted(csv_cols),
            "missed_parameters": sorted(exp_params - csv_cols),
            "unnecessary_parameters": sorted(csv_cols - exp_params),
            "shapes_missed": [e["shape"] for e in miss],
        })
        tot_exp += len(exp); tot_det += len(hit); tot_false += len(false_corr); tot_below += len(below)

    summary = {
        "applications_scored": len(rows),
        "expected_correlations": tot_exp, "detected_correlations": tot_det,
        "missed_correlations": tot_exp - tot_det, "missed_below_documented_threshold": tot_below,
        "false_correlations": tot_false,
        "correlation_recall": round(tot_det / tot_exp, 3) if tot_exp else None,
        "correlation_recall_excluding_below_threshold":
            round(tot_det / (tot_exp - tot_below), 3) if (tot_exp - tot_below) else None,
        "correlation_precision": (round(tot_det / (tot_det + tot_false), 3)
                                  if (tot_det + tot_false) else None),
        "unnecessary_csv_columns": sum(len(r["unnecessary_parameters"]) for r in rows),
        "missed_parameters": sum(len(r["missed_parameters"]) for r in rows),
        "dependent_values_miscast_as_parameters": sum(len(r["miscast_as_parameter"]) for r in rows),
    }
    return {"summary": summary, "rows": rows}


if __name__ == "__main__":
    out = score()
    (BENCH / "CORRELATION_SCORE.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    s = out["summary"]
    print(json.dumps(s, indent=1))
    print()
    for r in out["rows"]:
        print(f"{r['application']:24} exp={r['expected_correlations']} det={r['detected_correlations']} "
              f"miscast_param={r['miscast_as_parameter']} unnecessary_csv={r['unnecessary_parameters']}")
