"""APP14-APP26 - expansion pass. 13 further REAL API journeys across NEW domains and NEW shapes.

Every URL, method, status and response body was returned live by the real public API during capture in
the Claude browser pane. Producer bodies are COMPLETE; only terminal consumer bodies were shortened by
the harness (they produce nothing downstream), so the converter is never penalised for truncation.

Captured but DROPPED, with reason, so the corpus is not silently cherry-picked:
  iTunes Search, TheSportsDB, TheMealDB  - harness truncated their PRODUCER body (would score a false miss)
  CKAN / catalog.data.gov                - CORS blocked from the capture origin
  Platzi PUT (create->update)            - the API returned HTTP 500 on PUT; only create->retrieve kept
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_from_capture import build  # noqa: E402

BENCH = Path(__file__).resolve().parents[1]
S = "captured live via the Claude browser pane"


def A(u, st, d, b, m="GET", status=200, rb=None):
    e = {"u": u, "st": st, "d": d, "status": status, "b": b, "method": m}
    if rb:
        e["reqBody"] = rb
        e["reqMime"] = "application/json"
    return e


APPS = [
 ("app14_hackernews_topstories_to_item.har", {
  "meta": {"app": "Hacker News", "domain": "Social / news", "flow": "top stories -> open first story",
           "source": "https://hacker-news.firebaseio.com (public) - " + S,
           "provenance": "REAL_API_JOURNEY",
           "notes": "Producer is a ROOT-LEVEL ARRAY OF SCALAR NUMBERS."},
  "rows": [], "api": [
   A("https://hacker-news.firebaseio.com/v0/topstories.json?orderBy=%22$key%22&limitToFirst=5", 146577, 709,
     "[49823582,49820134,49826059,49824686,49823664]"),
   A("https://hacker-news.firebaseio.com/v0/item/49823582.json", 147286, 321,
     json.dumps({"by": "aaronday", "descendants": 124, "id": 49823582, "type": "story"}))]}),

 ("app15_openalex_referenced_works.har", {
  "meta": {"app": "OpenAlex", "domain": "Education / research", "flow": "list works -> open a referenced work",
           "source": "https://api.openalex.org (public) - " + S, "provenance": "REAL_API_JOURNEY",
           "notes": "Producer is an ARRAY OF SCALAR STRINGS; the consumer uses only the trailing id of "
                    "the produced URL, so the produced value CONTAINS the consumed value."},
  "rows": [], "api": [
   A("https://api.openalex.org/works?per-page=1&select=id,doi,title,referenced_works", 147607, 540,
     json.dumps({"meta": {"count": 327891184, "page": 1, "per_page": 1},
                 "results": [{"id": "https://openalex.org/W3038568908",
                              "doi": "https://doi.org/10.1585/pfr.15.2402039",
                              "title": "Radiation Resistant Camera System",
                              "referenced_works": ["https://openalex.org/W2069091362",
                                                   "https://openalex.org/W2151240562",
                                                   "https://openalex.org/W2527753843"]}]})),
   A("https://api.openalex.org/works/W2069091362?select=id,title", 148147, 340,
     json.dumps({"id": "https://openalex.org/W2069091362", "title": "Effects of DD and DT neutron irradiation"}))]}),

 ("app16_postcodes_random_to_lookup.har", {
  "meta": {"app": "postcodes.io", "domain": "Logistics / geo", "flow": "random postcode -> look it up",
           "source": "https://api.postcodes.io (public) - " + S, "provenance": "REAL_API_JOURNEY",
           "notes": "The produced value contains a SPACE and is URL-ENCODED in the consumer path."},
  "rows": [], "api": [
   A("https://api.postcodes.io/random/postcodes", 148487, 216,
     json.dumps({"status": 200, "result": {"postcode": "S13 7JT", "quality": 1, "country": "England",
                                           "region": "Yorkshire and The Humber", "outcode": "S13",
                                           "incode": "7JT", "admin_district": "Sheffield",
                                           "codes": {"admin_district": "E08000039", "lsoa": "E01007970"}}})),
   A("https://api.postcodes.io/postcodes/S13%207JT", 148703, 232,
     json.dumps({"status": 200, "result": {"postcode": "S13 7JT", "country": "England"}}))]}),

 ("app17_openbrewery_list_to_detail.har", {
  "meta": {"app": "Open Brewery DB", "domain": "Retail / hospitality", "flow": "list breweries -> open one",
           "source": "https://api.openbrewerydb.org (public) - " + S, "provenance": "REAL_API_JOURNEY",
           "notes": "UUID inside a root array of objects -> URL path."},
  "rows": [], "api": [
   A("https://api.openbrewerydb.org/v1/breweries?per_page=1", 148935, 5,
     json.dumps([{"id": "ae7b3174-8be8-4d53-a3a5-9b8240970eea", "name": "'s", "brewery_type": "brewpub",
                  "city": "Kronach", "state_province": "Bayern", "country": "Germany"}])),
   A("https://api.openbrewerydb.org/v1/breweries/ae7b3174-8be8-4d53-a3a5-9b8240970eea", 148939, 4,
     json.dumps({"id": "ae7b3174-8be8-4d53-a3a5-9b8240970eea", "name": "'s", "city": "Kronach"}))]}),

 ("app18_fhir_patient_search_to_read.har", {
  "meta": {"app": "HAPI FHIR", "domain": "Healthcare", "flow": "search patients -> read the patient",
           "source": "https://hapi.fhir.org (public FHIR R4 test server) - " + S,
           "provenance": "REAL_API_JOURNEY",
           "notes": "Nested Bundle.entry[].resource.id -> path; entry[].fullUrl also holds the whole "
                    "consumer URL. Public test server data."},
  "rows": [], "api": [
   A("https://hapi.fhir.org/baseR4/Patient?_count=1&_elements=id,name&_format=json", 148944, 591,
     json.dumps({"resourceType": "Bundle", "id": "26729662-257f-40fc-b6f9-05e30dcc0857",
                 "type": "searchset",
                 "link": [{"relation": "self",
                           "url": "https://hapi.fhir.org/baseR4/Patient?_count=1&_format=json"}],
                 "entry": [{"fullUrl": "https://hapi.fhir.org/baseR4/Patient/4202",
                            "resource": {"resourceType": "Patient", "id": "4202",
                                         "meta": {"versionId": "1"},
                                         "name": [{"use": "official", "family": "Saikia",
                                                   "given": ["Arunoday"]}]},
                            "search": {"mode": "match"}}]})),
   A("https://hapi.fhir.org/baseR4/Patient/4202?_elements=id,name&_format=json", 149534, 5,
     json.dumps({"resourceType": "Patient", "id": "4202", "meta": {"versionId": "1"}}))]}),

 ("app19_clinicaltrials_search_to_study.har", {
  "meta": {"app": "ClinicalTrials.gov", "domain": "Government / clinical research",
           "flow": "search studies -> open the study by NCT id",
           "source": "https://clinicaltrials.gov (public) - " + S, "provenance": "REAL_API_JOURNEY",
           "notes": "Deeply nested studies[].protocolSection.identificationModule.nctId -> path."},
  "rows": [], "api": [
   A("https://clinicaltrials.gov/api/v2/studies?pageSize=1&fields=NCTId,BriefTitle&format=json", 149540, 362,
     json.dumps({"studies": [{"protocolSection": {"identificationModule": {
                     "nctId": "NCT05604235",
                     "briefTitle": "Effectiveness of Oncological Physiotherapy"}}}],
                 "nextPageToken": "ZVNj7o2Elu8o3lpwWM-j4bbumo6QepFqYPim2fg"})),
   A("https://clinicaltrials.gov/api/v2/studies/NCT05604235?fields=NCTId,BriefTitle&format=json", 149901, 380,
     json.dumps({"protocolSection": {"identificationModule": {"nctId": "NCT05604235"}}}))]}),

 ("app20_gbif_species_search_to_names.har", {
  "meta": {"app": "GBIF", "domain": "Government / biodiversity science",
           "flow": "search species -> list its vernacular names",
           "source": "https://api.gbif.org (public) - " + S, "provenance": "REAL_API_JOURNEY",
           "notes": "results[0].key -> path. The same value also appears as speciesKey in the SAME "
                    "response (two candidate producer fields for one consumer)."},
  "rows": [], "api": [
   A("https://api.gbif.org/v1/species/search?q=puma%20concolor&limit=1", 150281, 708,
     json.dumps({"offset": 0, "limit": 1, "count": 554,
                 "results": [{"key": 116892593, "nubKey": 2435099, "parentKey": 116892589,
                              "genus": "Puma", "species": "Puma concolor", "speciesKey": 116892593,
                              "scientificName": "Puma concolor", "rank": "SPECIES"}]})),
   A("https://api.gbif.org/v1/species/116892593/vernacularNames?limit=2", 150989, 246,
     json.dumps({"offset": 0, "limit": 2, "endOfRecords": True,
                 "results": [{"taxonKey": 116892593, "vernacularName": "puma", "language": "eng"}]}))]}),

 ("app21_npm_search_to_package.har", {
  "meta": {"app": "npm registry", "domain": "Developer / API platform",
           "flow": "search packages -> open the package's latest manifest",
           "source": "https://registry.npmjs.org (public) - " + S, "provenance": "REAL_API_JOURNEY",
           "notes": "Nested objects[].package.name (a string, not an id) -> URL path."},
  "rows": [], "api": [
   A("https://registry.npmjs.org/-/v1/search?text=jmeter-report&size=1", 168170, 13,
     json.dumps({"objects": [{"downloads": {"monthly": 54724, "weekly": 11791},
                              "package": {"name": "performance-results-parser", "version": "0.0.10",
                                          "description": "Parse performance test results",
                                          "keywords": ["jmeter", "performance"]},
                              "score": {"final": 81.27738}}], "total": 53214})),
   A("https://registry.npmjs.org/performance-results-parser/latest", 168183, 2,
     json.dumps({"name": "performance-results-parser", "version": "0.0.10"}))]}),

 ("app22_crossref_works_to_doi.har", {
  "meta": {"app": "Crossref", "domain": "Education / scholarly publishing",
           "flow": "list works -> open the work by its DOI",
           "source": "https://api.crossref.org (public) - " + S, "provenance": "REAL_API_JOURNEY",
           "notes": "The DOI contains a SLASH, so the produced value spans TWO path segments."},
  "rows": [], "api": [
   A("https://api.crossref.org/works?rows=1&select=DOI,title", 168185, 1557,
     json.dumps({"status": "ok", "message-type": "work-list",
                 "message": {"total-results": 186898620,
                             "items": [{"DOI": "10.1002/9781119584414.ch4",
                                        "title": ["Complete Dental Cleaning"]}],
                             "items-per-page": 1}})),
   A("https://api.crossref.org/works/10.1002/9781119584414.ch4", 169743, 276,
     json.dumps({"status": "ok", "message-type": "work",
                 "message": {"publisher": "Wiley", "edition-number": "1"}}))]}),

 ("app23_platzi_create_to_retrieve.har", {
  "meta": {"app": "Platzi Fake Store", "domain": "E-commerce",
           "flow": "create a product -> retrieve the created product",
           "source": "https://api.escuelajs.co (public sandbox) - " + S, "provenance": "REAL_API_JOURNEY",
           "notes": "POST-created numeric id -> path (create -> retrieve)."},
  "rows": [], "api": [
   A("https://api.escuelajs.co/api/v1/products/", 170019, 1092,
     json.dumps({"id": 428, "title": "PerfProbe3", "slug": "perfprobe3", "price": 19,
                 "description": "perf",
                 "category": {"id": 1, "name": "Updated Category Name", "slug": "updated-category-name"},
                 "images": ["https://placehold.co/600x400"]}),
     m="POST", status=201,
     rb=json.dumps({"title": "PerfProbe3", "price": 19, "description": "perf", "categoryId": 1,
                    "images": ["https://placehold.co/600x400"]})),
   A("https://api.escuelajs.co/api/v1/products/428", 171111, 238,
     json.dumps({"id": 428, "title": "PerfProbe3", "price": 19}))]}),

 ("app24_deckofcards_shuffle_draw_shuffle.har", {
  "meta": {"app": "Deck of Cards API", "domain": "Gaming / entertainment",
           "flow": "new shuffled deck -> draw cards -> reshuffle the same deck",
           "source": "https://deckofcardsapi.com (public) - " + S, "provenance": "REAL_API_JOURNEY",
           "notes": "OPAQUE server-generated deck id consumed by TWO later requests (both path)."},
  "rows": [], "api": [
   A("https://deckofcardsapi.com/api/deck/new/shuffle/?deck_count=1", 171349, 281,
     json.dumps({"success": True, "deck_id": "hoe4kg03jrmq", "remaining": 52, "shuffled": True})),
   A("https://deckofcardsapi.com/api/deck/hoe4kg03jrmq/draw/?count=2", 171630, 269,
     json.dumps({"success": True, "deck_id": "hoe4kg03jrmq",
                 "cards": [{"code": "AH", "value": "ACE", "suit": "HEARTS"},
                           {"code": "9S", "value": "9", "suit": "SPADES"}], "remaining": 50})),
   A("https://deckofcardsapi.com/api/deck/hoe4kg03jrmq/shuffle/", 171899, 267,
     json.dumps({"success": True, "deck_id": "hoe4kg03jrmq", "remaining": 52, "shuffled": True}))]}),

 ("app25_swapi_film_to_character.har", {
  "meta": {"app": "SWAPI", "domain": "Media / entertainment",
           "flow": "open a film -> open its first character",
           "source": "https://swapi.info (public) - " + S, "provenance": "REAL_API_JOURNEY",
           "notes": "ARRAY OF SCALAR STRINGS holding absolute URLs -> requested verbatim."},
  "rows": [], "api": [
   A("https://swapi.info/api/films/1", 172167, 86,
     json.dumps({"title": "A New Hope", "episode_id": 4, "director": "George Lucas",
                 "release_date": "1977-05-25",
                 "characters": ["https://swapi.info/api/people/1", "https://swapi.info/api/people/2",
                                "https://swapi.info/api/people/3"],
                 "planets": ["https://swapi.info/api/planets/1"],
                 "url": "https://swapi.info/api/films/1"})),
   A("https://swapi.info/api/people/1", 172252, 48,
     json.dumps({"name": "Luke Skywalker", "height": "172", "gender": "male",
                 "homeworld": "https://swapi.info/api/planets/1"}))]}),

 ("app26_opentdb_token_to_questions.har", {
  "meta": {"app": "Open Trivia DB", "domain": "Gaming / media",
           "flow": "request a session token -> fetch questions with that token",
           "source": "https://opentdb.com (public) - " + S, "provenance": "REAL_API_JOURNEY",
           "notes": "Opaque 64-char server session token -> query parameter."},
  "rows": [], "api": [
   A("https://opentdb.com/api_token.php?command=request", 172300, 905,
     json.dumps({"response_code": 0, "response_message": "Token Generated Successfully!",
                 "token": "d23c01dff6f90c5e440739ca69c476173b42c9f52bcc1d02f837c61d140cc229"})),
   A("https://opentdb.com/api.php?amount=1&token=d23c01dff6f90c5e440739ca69c476173b42c9f52bcc1d02f837c61d140cc229",
     173205, 362,
     json.dumps({"response_code": 0, "results": [{"type": "multiple", "difficulty": "hard",
                                                  "category": "Celebrities"}]}))]}),
]

if __name__ == "__main__":
    (BENCH / "raw").mkdir(parents=True, exist_ok=True)
    for name, rec in APPS:
        (BENCH / "raw" / name.replace(".har", ".capture.json")).write_text(
            json.dumps(rec, indent=1), encoding="utf-8")
        out, n, hosts = build(rec, name)
        print(f"wrote {out.name}: {n} entries, {hosts} hosts")
