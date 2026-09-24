"""APP30-APP44 - second expansion. 15 further REAL workflows across new domains and new shapes.

All captured live in the Claude browser pane against real public APIs. Producer bodies are COMPLETE;
only terminal consumer bodies were shortened (they produce nothing downstream).

Disclosure: response bodies are re-serialized from the captured JSON, so key order and whitespace may
differ from the wire bytes; values and structure are exactly as returned.

Credential disclosure: restful-booker publishes admin/password123 in its own documentation as the
intended public entry point; those exact values are used. No real account, nothing bypassed.

Captured but DROPPED, with reason: dev.to (harness truncated its PRODUCER body), Binance / Deezer /
Pokemon TCG / REST Countries (CORS-blocked from the capture origin), Jikan (HTTP 504),
Nager.Date + Lemmy (producer truncated), CoinGecko (14 KB producer - swapped for Frankfurter).
Also BLOCKED by capture METHOD, not by the engine: JSON -> cookie. Browsers forbid setting the Cookie
header from fetch and HttpOnly cookies are invisible to JS, so a token->Cookie dependency cannot be
captured this way (restful-booker's PUT therefore uses its documented Basic auth instead).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_from_capture import build  # noqa: E402

BENCH = Path(__file__).resolve().parents[1]
S = "captured live via the Claude browser pane"
BASIC = "Basic YWRtaW46cGFzc3dvcmQxMjM="


def A(u, st, d, b, m="GET", status=200, rb=None, hdrs=None):
    e = {"u": u, "st": st, "d": d, "status": status, "b": b, "method": m}
    if rb is not None:
        e["reqBody"] = rb
        e["reqMime"] = "application/json"
    if hdrs:
        e["reqHeaders"] = hdrs
    return e


def M(app, domain, flow, source, notes=""):
    return {"app": app, "domain": domain, "flow": flow, "source": f"{source} - {S}",
            "provenance": "REAL_API_JOURNEY",
            "notes": notes or "Bodies re-serialized from the captured JSON; producer complete."}


HF_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
HF_DS = "m-a-p/FineFineWeb"
UK_FORCES = [("avon-and-somerset", "Avon and Somerset Constabulary"), ("bedfordshire", "Bedfordshire Police"),
             ("cambridgeshire", "Cambridgeshire Constabulary"), ("cheshire", "Cheshire Constabulary"),
             ("city-of-london", "City of London Police"), ("cleveland", "Cleveland Police"),
             ("cumbria", "Cumbria Constabulary"), ("derbyshire", "Derbyshire Constabulary"),
             ("devon-and-cornwall", "Devon & Cornwall Police"), ("dorset", "Dorset Police"),
             ("durham", "Durham Constabulary"), ("essex", "Essex Police"),
             ("gloucestershire", "Gloucestershire Constabulary"),
             ("greater-manchester", "Greater Manchester Police"), ("gwent", "Gwent Police"),
             ("hampshire", "Hampshire Constabulary"), ("dyfed-powys", "Dyfed-Powys Police"),
             ("hertfordshire", "Hertfordshire Constabulary"), ("humberside", "Humberside Police"),
             ("kent", "Kent Police"), ("lancashire", "Lancashire Constabulary"),
             ("leicestershire", "Leicestershire Police"), ("lincolnshire", "Lincolnshire Police"),
             ("merseyside", "Merseyside Police"), ("metropolitan", "Metropolitan Police Service"),
             ("norfolk", "Norfolk Constabulary"), ("north-wales", "North Wales Police"),
             ("north-yorkshire", "North Yorkshire Police"), ("northamptonshire", "Northamptonshire Police"),
             ("northumbria", "Northumbria Police"), ("nottinghamshire", "Nottinghamshire Police"),
             ("northern-ireland", "Police Service of Northern Ireland"), ("south-wales", "South Wales Police"),
             ("south-yorkshire", "South Yorkshire Police"), ("staffordshire", "Staffordshire Police"),
             ("suffolk", "Suffolk Constabulary"), ("surrey", "Surrey Police"), ("sussex", "Sussex Police"),
             ("thames-valley", "Thames Valley Police"), ("warwickshire", "Warwickshire Police"),
             ("west-mercia", "West Mercia Police"), ("west-midlands", "West Midlands Police"),
             ("west-yorkshire", "West Yorkshire Police"), ("wiltshire", "Wiltshire Police")]

APPS = [
 ("app30_restfulbooker_create_update_retrieve.har", {
  "meta": M("restful-booker", "Travel / booking",
            "authenticate -> create booking -> UPDATE it -> retrieve it",
            "https://restful-booker.herokuapp.com (public sandbox, documented test user)",
            "create->update->retrieve; the booking id has TWO consumers. The auth token is issued but "
            "never consumed (Basic auth is used for the PUT), so correlating it would be a false "
            "positive. Basic credential is Base64 of documented sandbox credentials."),
  "rows": [], "api": [
   A("https://restful-booker.herokuapp.com/auth", 30939, 274, json.dumps({"token": "ffb48ff29777745"}),
     m="POST", rb=json.dumps({"username": "admin", "password": "password123"})),
   A("https://restful-booker.herokuapp.com/booking", 31213, 261,
     json.dumps({"bookingid": 4248, "booking": {"firstname": "Perf", "lastname": "Probe",
                 "totalprice": 250, "depositpaid": True,
                 "bookingdates": {"checkin": "2026-03-01", "checkout": "2026-03-07"},
                 "additionalneeds": "Late checkout"}}),
     m="POST", rb=json.dumps({"firstname": "Perf", "lastname": "Probe", "totalprice": 250,
                              "depositpaid": True,
                              "bookingdates": {"checkin": "2026-03-01", "checkout": "2026-03-07"},
                              "additionalneeds": "Late checkout"})),
   A("https://restful-booker.herokuapp.com/booking/4248", 31473, 264,
     json.dumps({"firstname": "PerfUpdated", "lastname": "Probe", "totalprice": 399,
                 "depositpaid": False,
                 "bookingdates": {"checkin": "2026-03-02", "checkout": "2026-03-09"},
                 "additionalneeds": "Breakfast"}),
     m="PUT", hdrs=[{"name": "Authorization", "value": BASIC},
                    {"name": "Accept", "value": "application/json"}],
     rb=json.dumps({"firstname": "PerfUpdated", "lastname": "Probe", "totalprice": 399,
                    "depositpaid": False,
                    "bookingdates": {"checkin": "2026-03-02", "checkout": "2026-03-09"},
                    "additionalneeds": "Breakfast"})),
   A("https://restful-booker.herokuapp.com/booking/4248", 31737, 261,
     json.dumps({"firstname": "PerfUpdated", "lastname": "Probe", "totalprice": 399})),
  ]}),

 ("app31_huggingface_models.har", {
  "meta": M("Hugging Face Hub", "GenAI / AI model registry", "list models -> open the top model",
            "https://huggingface.co (public, no login)",
            "The model id CONTAINS A SLASH, so the produced value spans two path segments."),
  "rows": [], "api": [
   A("https://huggingface.co/api/models?limit=1&sort=downloads&direction=-1", 183866, 326,
     json.dumps([{"_id": "621ffdc136468d709f180294", "id": HF_MODEL, "likes": 6113, "private": False,
                  "downloads": 250598416, "pipeline_tag": "sentence-similarity",
                  "library_name": "sentence-transformers", "createdAt": "2022-03-02T23:29:05.000Z",
                  "modelId": HF_MODEL}])),
   A(f"https://huggingface.co/api/models/{HF_MODEL}", 184192, 410,
     json.dumps({"_id": "621ffdc136468d709f180294", "id": HF_MODEL, "private": False,
                 "pipeline_tag": "sentence-similarity"})),
  ]}),

 ("app32_huggingface_datasets.har", {
  "meta": M("Hugging Face Hub", "GenAI / AI dataset registry", "list datasets -> open the top dataset",
            "https://huggingface.co (public, no login)",
            "Dataset id also contains a slash (multi-segment path value)."),
  "rows": [], "api": [
   A("https://huggingface.co/api/datasets?limit=1&sort=downloads&direction=-1", 184603, 300,
     json.dumps([{"_id": "675d7e29e24babdf1842d270", "id": HF_DS, "author": "m-a-p",
                  "sha": "7fd92dc825a75cbff271a5a52eea0eda91a2c112", "likes": 190, "private": False,
                  "downloads": 3300506, "createdAt": "2024-12-14T12:46:33.000Z"}])),
   A(f"https://huggingface.co/api/datasets/{HF_DS}", 184903, 369,
     json.dumps({"_id": "675d7e29e24babdf1842d270", "id": HF_DS, "author": "m-a-p"})),
  ]}),

 ("app33_frankfurter_rate_date.har", {
  "meta": M("Frankfurter", "Finance / FX rates", "latest rates -> historical rates for the returned date",
            "https://api.frankfurter.dev (public, no login)",
            "The dependency is a server-returned DATE reused as a path segment."),
  "rows": [], "api": [
   A("https://api.frankfurter.dev/v1/latest?base=USD&symbols=EUR,GBP", 185288, 8,
     json.dumps({"amount": 1.0, "base": "USD", "date": "2026-09-23",
                 "rates": {"EUR": 0.87635, "GBP": 0.75322}})),
   A("https://api.frankfurter.dev/v1/2026-09-23?base=USD&symbols=EUR", 185296, 5,
     json.dumps({"amount": 1.0, "base": "USD", "date": "2026-09-23", "rates": {"EUR": 0.87635}})),
  ]}),

 ("app34_wikidata_search_to_entity.har", {
  "meta": M("Wikidata", "Knowledge graph / open data", "search entities -> fetch the entity by Q-id",
            "https://www.wikidata.org (public, no login)"),
  "rows": [], "api": [
   A("https://www.wikidata.org/w/api.php?action=wbsearchentities&search=Dublin&language=en&format=json&limit=1&origin=*",
     185301, 682,
     json.dumps({"searchinfo": {"search": "Dublin"},
                 "search": [{"id": "Q1761", "title": "Q1761", "pageid": 2302,
                             "concepturi": "http://www.wikidata.org/entity/Q1761",
                             "label": "Dublin", "description": "capital and largest city of Ireland"}],
                 "success": 1})),
   A("https://www.wikidata.org/w/api.php?action=wbgetentities&ids=Q1761&format=json&props=labels&languages=en&origin=*",
     185984, 474,
     json.dumps({"entities": {"Q1761": {"type": "item", "id": "Q1761",
                 "labels": {"en": {"language": "en", "value": "Dublin"}}}}, "success": 1})),
  ]}),

 ("app35_dummyjson_product_search.har", {
  "meta": M("DummyJSON", "E-commerce", "search products -> open the returned product",
            "https://dummyjson.com (public sandbox)"),
  "rows": [], "api": [
   A("https://dummyjson.com/products/search?q=phone&limit=1&select=id,title,brand", 186458, 397,
     json.dumps({"products": [{"id": 101, "title": "Apple AirPods Max Silver", "brand": "Apple"}],
                 "total": 23, "skip": 0, "limit": 1})),
   A("https://dummyjson.com/products/101?select=id,title", 186855, 365,
     json.dumps({"id": 101, "title": "Apple AirPods Max Silver"})),
  ]}),

 ("app36_diseasesh_country_iso3.har", {
  "meta": M("disease.sh", "Healthcare / public-health data",
            "country stats -> re-query by the returned ISO3 code",
            "https://disease.sh (public, no login)",
            "The dependent value 'IRL' is exactly 3 characters - at the documented floor boundary."),
  "rows": [], "api": [
   A("https://disease.sh/v3/covid-19/countries/Ireland?strict=true", 187220, 1374,
     json.dumps({"updated": 1790240502061, "country": "Ireland",
                 "countryInfo": {"_id": 372, "iso2": "IE", "iso3": "IRL", "lat": 53, "long": -8,
                                 "flag": "https://disease.sh/assets/img/flags/ie.png"},
                 "cases": 1734582, "deaths": 9491, "recovered": 1724921, "active": 170,
                 "population": 5020199, "continent": "Europe"})),
   A("https://disease.sh/v3/covid-19/countries/IRL", 188595, 196,
     json.dumps({"updated": 1790240502061, "country": "Ireland",
                 "countryInfo": {"_id": 372, "iso2": "IE", "iso3": "IRL"}})),
  ]}),

 ("app37_artic_artwork_search.har", {
  "meta": M("Art Institute of Chicago", "Culture / museum",
            "search artworks -> open the returned artwork", "https://api.artic.edu (public, no login)"),
  "rows": [], "api": [
   A("https://api.artic.edu/api/v1/artworks/search?q=cat&limit=1&fields=id,title", 188791, 211,
     json.dumps({"pagination": {"total": 133118, "limit": 1, "offset": 0, "current_page": 1},
                 "data": [{"_score": 92.31233, "id": 656,
                           "title": "Lion (One of a Pair, South Pedestal)"}],
                 "config": {"iiif_url": "https://www.artic.edu/iiif/2",
                            "website_url": "http://www.artic.edu"}})),
   A("https://api.artic.edu/api/v1/artworks/656?fields=id,title", 189002, 181,
     json.dumps({"data": {"id": 656, "title": "Lion (One of a Pair, South Pedestal)"}})),
  ]}),

 ("app38_github_tag_to_ref.har", {
  "meta": M("GitHub API", "Developer platform", "list tags -> resolve the tag's git ref",
            "https://api.github.com (public, unauthenticated)"),
  "rows": [], "api": [
   A("https://api.github.com/repos/apache/jmeter/tags?per_page=1", 189183, 540,
     json.dumps([{"name": "v5.6.3-rc2",
                  "zipball_url": "https://api.github.com/repos/apache/jmeter/zipball/refs/tags/v5.6.3-rc2",
                  "commit": {"sha": "34a2785748e9e0b14702595e8682c387869deda3"},
                  "node_id": "MDM6UmVmNjg4MzUyOnJlZnMvdGFncy92NS42LjMtcmMy"}])),
   A("https://api.github.com/repos/apache/jmeter/git/ref/tags/v5.6.3-rc2", 189723, 346,
     json.dumps({"ref": "refs/tags/v5.6.3-rc2",
                 "node_id": "MDM6UmVmNjg4MzUyOnJlZnMvdGFncy92NS42LjMtcmMy"})),
  ]}),

 ("app39_tvmaze_show_to_seasons.har", {
  "meta": M("TVMaze", "Media / TV", "search a show -> list its seasons",
            "https://api.tvmaze.com (public, no login)",
            "The producer also carries a _links.self HATEOAS href for the same resource."),
  "rows": [], "api": [
   A("https://api.tvmaze.com/singlesearch/shows?q=girls", 205089, 19,
     json.dumps({"id": 139, "url": "https://www.tvmaze.com/shows/139/girls", "name": "Girls",
                 "type": "Scripted", "language": "English", "genres": ["Drama", "Romance"],
                 "status": "Ended", "runtime": 30, "premiered": "2012-04-15",
                 "network": {"id": 8, "name": "HBO"},
                 "externals": {"tvrage": 30124, "thetvdb": 220411, "imdb": "tt1723816"},
                 "_links": {"self": {"href": "https://api.tvmaze.com/shows/139"},
                            "previousepisode": {"href": "https://api.tvmaze.com/episodes/1079686"}}})),
   A("https://api.tvmaze.com/shows/139/seasons", 205108, 5,
     json.dumps([{"id": 650, "number": 1, "episodeOrder": 10, "premiereDate": "2012-04-15"}])),
  ]}),

 ("app40_cratesio_search_to_crate.har", {
  "meta": M("crates.io", "Developer platform", "list crates -> open the top crate",
            "https://crates.io (public, no login)",
            "The dependent value is a package NAME, not an id - a direct check that an ordinary "
            "lowercase name is not mistaken for catalog data."),
  "rows": [], "api": [
   A("https://crates.io/api/v1/crates?per_page=1&sort=downloads", 205114, 905,
     json.dumps({"crates": [{"id": "hashbrown", "name": "hashbrown",
                             "updated_at": "2026-05-09T04:35:04.251Z", "downloads": 2510962353,
                             "default_version": "0.17.1", "num_versions": 56, "yanked": False,
                             "max_version": "0.17.1", "newest_version": "0.17.1",
                             "description": "A Rust port of Google's SwissTable hash map",
                             "repository": "https://github.com/rust-lang/hashbrown"}],
                 "meta": {"total": 338773}})),
   A("https://crates.io/api/v1/crates/hashbrown", 206019, 859,
     json.dumps({"crate": {"id": "hashbrown", "name": "hashbrown", "max_version": "0.17.1"}})),
  ]}),

 ("app41_openverse_image_search.har", {
  "meta": M("Openverse", "Media / openly-licensed images",
            "search images -> open the returned image", "https://api.openverse.org (public, no login)",
            "UUID inside a results array; the producer also carries detail_url, the FULL consumer URL."),
  "rows": [], "api": [
   A("https://api.openverse.org/v1/images/?q=cat&page_size=1", 207813, 53,
     json.dumps({"result_count": 240, "page_count": 240, "page_size": 1, "page": 1,
                 "results": [{"id": "1c5442f6-6bb6-4ab7-b603-f598e7579dd2", "title": "Cat Fish 2",
                              "url": "https://live.staticflickr.com/3313/3481540500_c846c62863_b.jpg",
                              "creator": "admiller", "license": "by", "license_version": "2.0",
                              "provider": "flickr", "source": "flickr",
                              "detail_url": "https://api.openverse.org/v1/images/1c5442f6-6bb6-4ab7-b603-f598e7579dd2/",
                              "height": 1024, "width": 716}]})),
   A("https://api.openverse.org/v1/images/1c5442f6-6bb6-4ab7-b603-f598e7579dd2/", 207866, 52,
     json.dumps({"id": "1c5442f6-6bb6-4ab7-b603-f598e7579dd2", "title": "Cat Fish 2"})),
  ]}),

 ("app42_dummyjson_put_producer.har", {
  "meta": M("DummyJSON", "E-commerce",
            "search a product -> UPDATE it (PUT) -> retrieve it",
            "https://dummyjson.com (public sandbox)",
            "PUT is itself a PRODUCER of the id, which is therefore emitted by TWO producers "
            "(the search and the update) and consumed by the retrieve."),
  "rows": [], "api": [
   A("https://dummyjson.com/products/search?q=laptop&limit=1&select=id,title", 207918, 355,
     json.dumps({"products": [{"id": 78, "title": "Apple MacBook Pro 14 Inch Space Grey"}],
                 "total": 5, "skip": 0, "limit": 1})),
   A("https://dummyjson.com/products/78", 208273, 689,
     json.dumps({"id": 78, "title": "PerfUpdatedTitle", "price": 1999.99, "stock": 24,
                 "rating": 3.65, "brand": "Apple", "category": "laptops"}),
     m="PUT", rb=json.dumps({"title": "PerfUpdatedTitle"})),
   A("https://dummyjson.com/products/78?select=id,title", 208962, 421,
     json.dumps({"id": 78, "title": "Apple MacBook Pro 14 Inch Space Grey"})),
  ]}),

 ("app43_ukpolice_forces.har", {
  "meta": M("UK Police Data", "Government / policing", "list forces -> open a force",
            "https://data.police.uk (public, no login)",
            "The dependent value is a hyphenated SLUG ('avon-and-somerset') with no digits - the "
            "direct regression check for the tightened coded-id classifier."),
  "rows": [], "api": [
   A("https://data.police.uk/api/forces", 228103, 208,
     json.dumps([{"id": i, "name": n} for i, n in UK_FORCES])),
   A("https://data.police.uk/api/forces/avon-and-somerset", 228310, 183,
     json.dumps({"id": "avon-and-somerset", "name": "Avon and Somerset Constabulary",
                 "telephone": "101", "url": "http://www.avonandsomerset.police.uk"})),
  ]}),

 ("app44_cocktaildb_random_lookup.har", {
  "meta": M("TheCocktailDB", "Food & beverage", "random drink -> look it up by the returned id",
            "https://www.thecocktaildb.com (public, no login)"),
  "rows": [], "api": [
   A("https://www.thecocktaildb.com/api/json/v1/1/random.php", 228494, 596,
     json.dumps({"drinks": [{"idDrink": "13020", "strDrink": "Sangria", "strDrinkAlternate": None,
                             "strCategory": "Punch / Party Drink", "strAlcoholic": "Alcoholic",
                             "strGlass": "Pitcher",
                             "strInstructions": "Mix all together in a pitcher and refrigerate.",
                             "strDrinkThumb": "https://www.thecocktaildb.com/images/media/drink/xrvxpp1441249280.jpg",
                             "strIngredient1": "Red wine", "strIngredient2": "Sugar",
                             "strIngredient3": "Orange juice", "strIngredient4": "Lemon juice",
                             "strMeasure1": "1 bottle ", "strMeasure2": "1/2 cup ",
                             "dateModified": "2015-09-03 04:01:20"}]})),
   A("https://www.thecocktaildb.com/api/json/v1/1/lookup.php?i=13020", 229090, 1490,
     json.dumps({"drinks": [{"idDrink": "13020", "strDrink": "Sangria"}]})),
  ]}),
]

if __name__ == "__main__":
    (BENCH / "raw").mkdir(parents=True, exist_ok=True)
    for name, rec in APPS:
        (BENCH / "raw" / name.replace(".har", ".capture.json")).write_text(
            json.dumps(rec, indent=1), encoding="utf-8")
        out, n, hosts = build(rec, name)
        print(f"wrote {out.name}: {n} entries, {hosts} hosts")
