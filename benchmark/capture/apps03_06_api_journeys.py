"""APP03-APP06 - REAL API journeys captured live from the browser pane against public APIs.

These are API-ONLY journeys (no browser UI), so they carry no static-asset / analytics noise; they exist
to measure CORRELATION across different real dependency SHAPES. Provenance is stamped
REAL_API_JOURNEY so they are never merged with the full browser captures (APP01/APP02) or with the
hand-authored synthetic fixtures.

Every URL, status and response body below was returned live by the real public API during capture.
Bodies are verbatim as captured. Each journey is deliberately limited to steps whose PRODUCER body was
captured COMPLETE, so the tool is never penalised for a body this harness truncated.

Dependency shape per app:
  APP03 PokeAPI        results[0].url  -> used verbatim AS the next request URL   (absolute-URL HATEOAS)
  APP04 OpenFoodFacts  products[0].code-> path segment /api/v2/product/<code>      (string id -> path)
  APP05 reqres.in      data[0].id      -> path segment /api/users/<id>             (SMALL numeric id -> path)
  APP06 Nominatim      place_id        -> query parameter ?place_id=<id>           (numeric id -> query)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_from_capture import build  # noqa: E402

BENCH = Path(__file__).resolve().parents[1]
SRC = "captured live from the public API via the Claude browser pane"

APPS = [
 ("app03_pokeapi_list_to_detail.har", {
  "meta": {"app": "PokeAPI", "domain": "Media / gaming catalogue",
           "flow": "list resources -> open resource by returned URL",
           "source": "https://pokeapi.co (public, no login) - " + SRC,
           "provenance": "REAL_API_JOURNEY",
           "notes": "API-only journey; no browser UI noise. Bodies verbatim as returned."},
  "rows": [],
  "api": [
   {"u": "https://pokeapi.co/api/v2/pokemon?limit=2&offset=0", "st": 313, "d": 497, "status": 200,
    "b": json.dumps({"count": 1351, "next": "https://pokeapi.co/api/v2/pokemon?offset=2&limit=2",
                     "previous": None, "results": [
                        {"name": "bulbasaur", "url": "https://pokeapi.co/api/v2/pokemon/1/"},
                        {"name": "ivysaur", "url": "https://pokeapi.co/api/v2/pokemon/2/"}]})},
   {"u": "https://pokeapi.co/api/v2/pokemon/1/", "st": 810, "d": 1291, "status": 200,
    "b": json.dumps({"id": 1, "name": "bulbasaur", "base_experience": 64, "height": 7,
                     "is_default": True, "order": 1, "weight": 69})},
  ]}),

 ("app04_openfoodfacts_search_to_product.har", {
  "meta": {"app": "OpenFoodFacts", "domain": "Retail / food",
           "flow": "search products by category -> open product by returned code",
           "source": "https://world.openfoodfacts.org (public, no login) - " + SRC,
           "provenance": "REAL_API_JOURNEY",
           "notes": "API-only journey; no browser UI noise. Bodies verbatim as returned."},
  "rows": [],
  "api": [
   {"u": "https://world.openfoodfacts.org/api/v2/search?categories_tags_en=Breakfast%20cereals&fields=code,product_name&page_size=2",
    "st": 2478, "d": 1119, "status": 200,
    "b": json.dumps({"count": 27303, "page": 1, "page_count": 2, "page_size": 2, "skip": 0,
                     "products": [{"code": "3168930010265", "product_name": "cruesly melange de noix"},
                                  {"code": "3229820160672", "product_name": "Croustillant Chocolat"}]})},
   {"u": "https://world.openfoodfacts.org/api/v2/product/3168930010265?fields=code,product_name,brands",
    "st": 3597, "d": 174, "status": 200,
    "b": json.dumps({"code": "3168930010265", "status": 1, "status_verbose": "product found",
                     "product": {"brands": "PEPSICO FRANCE, Quaker", "code": "3168930010265",
                                 "product_name": "cruesly melange de noix"}})},
  ]}),

 ("app05_reqres_list_to_user.har", {
  "meta": {"app": "reqres.in", "domain": "SaaS / demo REST service",
           "flow": "list users -> open user by returned id",
           "source": "https://reqres.in (public demo API, no login) - " + SRC,
           "provenance": "REAL_API_JOURNEY",
           "notes": ("API-only journey; no browser UI noise. NOTE: the dependent id is the single "
                     "digit 3, below the converter's documented minimum correlatable length.")},
  "rows": [],
  "api": [
   {"u": "https://reqres.in/api/users?page=2&per_page=2", "st": 3772, "d": 459, "status": 200,
    "b": json.dumps({"page": 2, "per_page": 2, "total": 12, "total_pages": 6, "data": [
        {"id": 3, "email": "emma.wong@reqres.in", "first_name": "Emma", "last_name": "Wong",
         "avatar": "https://reqres.in/img/faces/3-image.jpg"},
        {"id": 4, "email": "eve.holt@reqres.in", "first_name": "Eve", "last_name": "Holt",
         "avatar": "https://reqres.in/img/faces/4-image.jpg"}]})},
   {"u": "https://reqres.in/api/users/3", "st": 4230, "d": 376, "status": 200,
    "b": json.dumps({"data": {"id": 3, "email": "emma.wong@reqres.in", "first_name": "Emma",
                              "last_name": "Wong", "avatar": "https://reqres.in/img/faces/3-image.jpg"}})},
  ]}),

 ("app06_nominatim_search_to_details.har", {
  "meta": {"app": "Nominatim (OpenStreetMap)", "domain": "Geo / logistics",
           "flow": "search place -> open place details by returned place_id",
           "source": "https://nominatim.openstreetmap.org (public, no login) - " + SRC,
           "provenance": "REAL_API_JOURNEY",
           "notes": "API-only journey; no browser UI noise. Bodies verbatim as returned."},
  "rows": [],
  "api": [
   {"u": "https://nominatim.openstreetmap.org/search?q=Dublin&format=json&limit=1",
    "st": 4606, "d": 42, "status": 200,
    "b": json.dumps([{"place_id": 275905280, "osm_type": "relation", "osm_id": 1109531,
                      "lat": "53.3493795", "lon": "-6.2605593", "class": "boundary",
                      "type": "administrative", "place_rank": 14, "name": "Dublin",
                      "display_name": "Dublin, County Dublin, Leinster, Ireland"}])},
   {"u": "https://nominatim.openstreetmap.org/details?place_id=275905280&format=json&addressdetails=0",
    "st": 4648, "d": 490, "status": 200,
    "b": json.dumps({"place_id": 275905280, "parent_place_id": 276481818, "osm_type": "N",
                     "osm_id": 4031270667, "category": "building", "type": "yes",
                     "localname": "Maes yr Allt", "country_code": "gb", "rank_address": 30})},
  ]}),
]

if __name__ == "__main__":
    (BENCH / "raw").mkdir(parents=True, exist_ok=True)
    for name, rec in APPS:
        (BENCH / "raw" / name.replace(".har", ".capture.json")).write_text(
            json.dumps(rec, indent=1), encoding="utf-8")
        out, n, hosts = build(rec, name)
        print(f"wrote {out.name}: {n} entries, {hosts} hosts")
