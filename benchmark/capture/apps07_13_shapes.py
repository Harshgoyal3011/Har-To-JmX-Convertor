"""APP07-APP13 - REAL API journeys captured live, chosen for NEW correlation SHAPES.

Every URL, method, status, request body, request header and response body below was produced by a real
public API during capture in the Claude browser pane. Nothing is invented.

Disclosures:
  * These are API-only journeys (no browser UI), so they carry no static/analytics noise. Provenance is
    stamped REAL_API_JOURNEY.
  * dummyjson and restful-booker are public TEST SANDBOXES whose credentials are published in their own
    documentation as the intended public entry point; the login calls below use exactly those. No real
    account, no access control bypassed.
  * Two consumer response bodies were shortened by the harness (marked in `notes`). Only CONSUMER bodies
    were shortened - every PRODUCER body is complete, so the converter is never penalised for harness
    truncation. themealdb was captured but DROPPED from the corpus because its producer body was
    truncated, which would have produced a false "missed correlation".
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_from_capture import build  # noqa: E402

BENCH = Path(__file__).resolve().parents[1]
SRC = "captured live via the Claude browser pane"
JWT = ("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpZCI6MSwidXNlcm5hbWUiOiJlbWlseXMiLCJlbWFpbCI6ImVtaWx5"
       "LmpvaG5zb25AeC5kdW1teWpzb24uY29tIiwiaWF0IjoxNzkwMjI1MzI2LCJleHAiOjE3OTAyMjcxMjZ9."
       "Yp1FajaS-7kfMvhRlEtZFsie4p2xE6F7twlzPg8i3Co")

APPS = [
 # ---- JWT -> Authorization header, producer POST, producer/consumer names differ (shapes 4,8,14,18)
 ("app07_dummyjson_login_to_me.har", {
  "meta": {"app": "DummyJSON", "domain": "SaaS / demo commerce API",
           "flow": "login -> fetch own profile with the issued bearer token",
           "source": "https://dummyjson.com (public sandbox, documented test user) - " + SRC,
           "provenance": "REAL_API_JOURNEY",
           "notes": "Consumer (/auth/me) body shortened by the harness to the first fields; it produces "
                    "nothing downstream. Producer body complete."},
  "rows": [],
  "api": [
   {"u": "https://dummyjson.com/auth/login", "m": "POST", "st": 287, "d": 973, "status": 200,
    "reqBody": json.dumps({"username": "emilys", "password": "emilyspass", "expiresInMins": 30}),
    "reqMime": "application/json",
    "b": json.dumps({"accessToken": JWT, "id": 1, "username": "emilys",
                     "email": "emily.johnson@x.dummyjson.com", "firstName": "Emily",
                     "lastName": "Johnson", "gender": "female"})},
   {"u": "https://dummyjson.com/auth/me", "m": "GET", "st": 1260, "d": 643, "status": 200,
    "reqHeaders": [{"name": "Authorization", "value": "Bearer " + JWT},
                   {"name": "Accept", "value": "application/json"}],
    "b": json.dumps({"id": 1, "firstName": "Emily", "lastName": "Johnson", "username": "emilys",
                     "email": "emily.johnson@x.dummyjson.com", "role": "admin"})},
  ]}),

 # ---- POST create -> numeric generated id -> URL path (shapes 1,11,18,25)
 ("app08_jsonplaceholder_create_to_comments.har", {
  "meta": {"app": "JSONPlaceholder", "domain": "Generic web API",
           "flow": "create a post -> read the comments of the created post",
           "source": "https://jsonplaceholder.typicode.com (public) - " + SRC,
           "provenance": "REAL_API_JOURNEY", "notes": "Bodies verbatim."},
  "rows": [],
  "api": [
   {"u": "https://jsonplaceholder.typicode.com/posts", "m": "POST", "st": 1904, "d": 1008, "status": 201,
    "reqBody": json.dumps({"title": "perf", "body": "x", "userId": 7}), "reqMime": "application/json",
    "b": json.dumps({"title": "perf", "body": "x", "userId": 7, "id": 101})},
   {"u": "https://jsonplaceholder.typicode.com/posts/101/comments", "m": "GET", "st": 2912, "d": 681,
    "status": 200, "b": "[]"},
  ]}),

 # ---- HATEOAS: array element holding an ABSOLUTE URL -> requested verbatim (shapes 6,10,24)
 ("app09_rickandmorty_episode_to_character.har", {
  "meta": {"app": "Rick and Morty API", "domain": "Media / entertainment catalogue",
           "flow": "open an episode -> open the first character it links to",
           "source": "https://rickandmortyapi.com (public) - " + SRC,
           "provenance": "REAL_API_JOURNEY",
           "notes": "Consumer (character) body shortened by the harness; producer body complete."},
  "rows": [],
  "api": [
   {"u": "https://rickandmortyapi.com/api/episode/1", "m": "GET", "st": 73212, "d": 10, "status": 200,
    "b": json.dumps({"id": 1, "name": "Pilot", "air_date": "December 2, 2013", "episode": "S01E01",
                     "characters": ["https://rickandmortyapi.com/api/character/1",
                                    "https://rickandmortyapi.com/api/character/2",
                                    "https://rickandmortyapi.com/api/character/35"],
                     "url": "https://rickandmortyapi.com/api/episode/1",
                     "created": "2017-11-10T12:56:33.798Z"})},
   {"u": "https://rickandmortyapi.com/api/character/1", "m": "GET", "st": 73222, "d": 251, "status": 200,
    "b": json.dumps({"id": 1, "name": "Rick Sanchez", "status": "Alive", "species": "Human"})},
  ]}),

 # ---- UUID -> query parameter (shapes 2,13)
 ("app10_httpbin_uuid_to_query.har", {
  "meta": {"app": "httpbin", "domain": "Generic HTTP service",
           "flow": "obtain a server-generated UUID -> send it as a trace parameter",
           "source": "https://httpbin.org (public) - " + SRC,
           "provenance": "REAL_API_JOURNEY", "notes": "Bodies verbatim."},
  "rows": [],
  "api": [
   {"u": "https://httpbin.org/uuid", "m": "GET", "st": 36137, "d": 743, "status": 200,
    "b": json.dumps({"uuid": "31bcf27e-5e87-47c1-bb31-d9f6a1acf6b9"})},
   {"u": "https://httpbin.org/anything?trace=31bcf27e-5e87-47c1-bb31-d9f6a1acf6b9", "m": "GET",
    "st": 36880, "d": 568, "status": 200,
    "b": json.dumps({"args": {"trace": "31bcf27e-5e87-47c1-bb31-d9f6a1acf6b9"}, "method": "GET",
                     "url": "https://httpbin.org/anything?trace=31bcf27e-5e87-47c1-bb31-d9f6a1acf6b9"})},
  ]}),

 # ---- ONE producer -> TWO distinct values, both consumed as query params (shapes 2,20)
 ("app11_openmeteo_geocode_to_forecast.har", {
  "meta": {"app": "Open-Meteo", "domain": "Geo / weather",
           "flow": "geocode a city -> request the forecast at the returned coordinates",
           "source": "https://open-meteo.com (public) - " + SRC,
           "provenance": "REAL_API_JOURNEY", "notes": "Bodies verbatim."},
  "rows": [],
  "api": [
   {"u": "https://geocoding-api.open-meteo.com/v1/search?name=Dublin&count=1&language=en&format=json",
    "m": "GET", "st": 37448, "d": 811, "status": 200,
    "b": json.dumps({"results": [{"id": 2964574, "name": "Dublin", "latitude": 53.33306,
                                  "longitude": -6.24889, "elevation": 17.0, "country_code": "IE",
                                  "timezone": "Europe/Dublin", "population": 1024027,
                                  "country": "Ireland"}], "generationtime_ms": 0.39839745})},
   {"u": "https://api.open-meteo.com/v1/forecast?latitude=53.33306&longitude=-6.24889&current=temperature_2m",
    "m": "GET", "st": 38258, "d": 792, "status": 200,
    "b": json.dumps({"latitude": 53.329914, "longitude": -6.2360687, "timezone": "GMT",
                     "current": {"time": "2026-09-24T04:45", "temperature_2m": 12.9}})},
  ]}),

 # ---- producer value EMBEDDED inside a larger consumer string: osm_ids=R<osm_id> (shape 23)
 ("app12_nominatim_osmid_embedded.har", {
  "meta": {"app": "Nominatim (OpenStreetMap)", "domain": "Geo / logistics",
           "flow": "search a place -> look it up by a type-prefixed OSM id (R<osm_id>)",
           "source": "https://nominatim.openstreetmap.org (public) - " + SRC,
           "provenance": "REAL_API_JOURNEY",
           "notes": "The lookup legitimately returned an empty array; the dependency is in the REQUEST."},
  "rows": [],
  "api": [
   {"u": "https://nominatim.openstreetmap.org/search?q=Trinity+College+Dublin&format=json&limit=1",
    "m": "GET", "st": 75127, "d": 598, "status": 200,
    "b": json.dumps([{"place_id": 396742295, "osm_type": "relation", "osm_id": 311466843,
                      "lat": "53.3438", "lon": "-6.2546", "class": "amenity", "type": "university",
                      "name": "Trinity College Dublin",
                      "display_name": "Trinity College Dublin, College Green, Dublin, Ireland"}])},
   {"u": "https://nominatim.openstreetmap.org/lookup?osm_ids=R311466843&format=json", "m": "GET",
    "st": 75725, "d": 958, "status": 200, "b": "[]"},
  ]}),

 # ---- opaque token (POST) + POST-created numeric id -> path  (shapes 16,11,18,1,25)
 ("app13_restfulbooker_auth_create_read.har", {
  "meta": {"app": "restful-booker", "domain": "Travel / booking",
           "flow": "authenticate -> create a booking -> read the created booking",
           "source": "https://restful-booker.herokuapp.com (public sandbox, documented test user) - " + SRC,
           "provenance": "REAL_API_JOURNEY", "notes": "Bodies verbatim."},
  "rows": [],
  "api": [
   {"u": "https://restful-booker.herokuapp.com/auth", "m": "POST", "st": 1202, "d": 267, "status": 200,
    "reqBody": json.dumps({"username": "admin", "password": "password123"}),
    "reqMime": "application/json", "b": json.dumps({"token": "817d15644a2398c"})},
   {"u": "https://restful-booker.herokuapp.com/booking", "m": "POST", "st": 1469, "d": 252, "status": 200,
    "reqBody": json.dumps({"firstname": "Perf", "lastname": "Test", "totalprice": 111,
                           "depositpaid": True,
                           "bookingdates": {"checkin": "2026-01-01", "checkout": "2026-01-05"},
                           "additionalneeds": "Breakfast"}),
    "reqMime": "application/json",
    "b": json.dumps({"bookingid": 5454,
                     "booking": {"firstname": "Perf", "lastname": "Test", "totalprice": 111,
                                 "depositpaid": True,
                                 "bookingdates": {"checkin": "2026-01-01", "checkout": "2026-01-05"},
                                 "additionalneeds": "Breakfast"}})},
   {"u": "https://restful-booker.herokuapp.com/booking/5454", "m": "GET", "st": 1721, "d": 253,
    "status": 200,
    "b": json.dumps({"firstname": "Perf", "lastname": "Test", "totalprice": 111, "depositpaid": True,
                     "bookingdates": {"checkin": "2026-01-01", "checkout": "2026-01-05"},
                     "additionalneeds": "Breakfast"})},
  ]}),
]


def _normalise(rec: dict) -> dict:
    """map the capture keys used above onto build_from_capture's schema"""
    for a in rec["api"]:
        a["method"] = a.pop("m", "GET")
        if "reqHeaders" in a:
            a["reqHeaders"] = a["reqHeaders"]
    return rec


if __name__ == "__main__":
    (BENCH / "raw").mkdir(parents=True, exist_ok=True)
    for name, rec in APPS:
        rec = _normalise(rec)
        (BENCH / "raw" / name.replace(".har", ".capture.json")).write_text(
            json.dumps(rec, indent=1), encoding="utf-8")
        out, n, hosts = build(rec, name)
        print(f"wrote {out.name}: {n} entries, {hosts} hosts")
