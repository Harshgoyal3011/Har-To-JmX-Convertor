"""APP01 - OpenLibrary (Library / public catalogue). REAL browser capture.

Journey (a PE-meaningful flow with a genuine server->client->server dependency):
    search books  ->  open work (key returned by search)  ->  list editions of that work

Provenance: every row below was observed in the browser pane on openlibrary.org via the Resource
Timing API; the three /*.json rows are real responses from the public OpenLibrary API captured in the
same session. Nothing is invented.

Disclosed normalization (raw -> normalized):
  * The API journey was issued ~218s after page load because of interactive instrumentation. Real user
    think time is not 218s, so in the NORMALIZED har the inter-phase gap is compressed to 4s. Timings
    WITHIN each phase are untouched. raw/ keeps the original offsets.
  * Duplicate instrumentation probes (repeat runs of the same journey) are dropped; one journey kept.
  * Response bodies are retained only for the JSON API responses; the HTML document body is NOT
    retained (size), which is recorded in the HAR comment.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from har_builder import write_har  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]

# type|startTimeMs|durationMs|transferSize|url   (verbatim from performance.getEntriesByType)
LINES = """navigation|0|9997|19567|https://openlibrary.org/search?q=performance+engineering
link|3665|285|4325|https://openlibrary.org/static/build/css/tokens.css?v=eea388d7418c955de621fe0afbfd7484
link|3666|285|2678|https://openlibrary.org/static/build/css/ol-components.css?v=534d6babd1fa6d19ba017b8c253a99bb
link|3666|544|41642|https://openlibrary.org/static/build/css/page-user.css?v=3b2f71f4a3ba0325ee22f161066bc5ca
script|3666|856|11999|https://openlibrary.org/cdn/archive.org/donate.js
img|3666|1233|9721|https://openlibrary.org/static/images/ia-logo.svg?v=a01876b378eb260334ee915282df715b
img|3666|2226|7983|https://openlibrary.org/static/images/openlibrary-logo-tighter.svg
img|3666|1941|0|https://covers.openlibrary.org/b/id/1878858-M.jpg
img|3666|1945|0|https://covers.openlibrary.org/b/id/55146-M.jpg
img|3666|2226|457|https://openlibrary.org/static/images/icons/avatar_book-sm.png
img|3666|3432|0|https://covers.openlibrary.org/b/id/8211535-M.jpg
script|3666|592|1364|https://openlibrary.org/static/build/js/all.js?v=6cdf20da8def13255c209302d992cb75
script|3666|1944|15427|https://openlibrary.org/cdn/archive.org/athena.js
script|3667|1233|145692|https://openlibrary.org/static/build/components/production/ol-components.js?v=a3c7cc6da1a4c7c1e7cd0c8127288814
script|4219|4434|0|https://apollo.archive.org/js/container_7cLc1b4U.js
iframe|4527|881|0|https://archive.org/includes/donate.php?as_page=1&referer=https%3A%2F%2Fopenlibrary.org%2Fsearch%3Fq%3Dperformance%2Bengineering&platform=ol&donation-identifier=MC44MDg0NjEzODIyMDk3MzUy
other|4537|4099|21752|https://openlibrary.org/static/icons/sprite.svg?v=002e98681eadabf2907f88458cfb35c8
css|4556|4080|709|https://openlibrary.org/static/images/search-icon.svg
css|4557|5287|799|https://openlibrary.org/static/images/icons/octicon-link-external-24.svg
css|4558|5431|553|https://openlibrary.org/static/images/icons/icon_dropit.png
script|5615|555|985|https://openlibrary.org/static/build/components/production/assets/chunk-CMxvf4Kt.js
script|5616|902|696|https://openlibrary.org/static/build/components/production/assets/defineProperty-BbfpZ9Tg.js
script|5617|930|87046|https://openlibrary.org/static/build/js/main.BetajRup.js
script|5617|1309|1085|https://openlibrary.org/static/build/js/chunk.BLj-jMpM.js
script|5617|1477|35701|https://openlibrary.org/static/build/js/jquery.DSlugHSX.js
script|5617|1749|1291|https://openlibrary.org/static/build/js/jsdef.BlL0E1r-.js
script|5618|1749|1526|https://openlibrary.org/static/build/js/utils.DzlhbAEF.js
script|5618|1749|634|https://openlibrary.org/static/build/js/nonjquery_utils.CMj587y-.js
script|5618|2451|1089|https://openlibrary.org/static/build/js/ol.analytics.BIM9gngX.js
script|5618|2452|2735|https://openlibrary.org/static/build/js/searchFacets.oWHONxBa.js
link|5619|552|3905|https://openlibrary.org/static/build/js/main.B0H1m7CK.css
css|6563|3430|2302|https://openlibrary.org/static/images/icons/open-book.svg
script|6673|1398|1364|https://openlibrary.org/static/build/js/all.js
fetch|8141|837|0|https://sink.archive.org/api/82/envelope/?sentry_version=7&sentry_key=8470b9d8af98fa200a09162f2e30ac87&sentry_client=sentry.javascript.browser%2F10.60.0
beacon|8156|813|0|https://athena.archive.org/0.gif?cache_bust=0.9688383277926913&server_ms=0.0&server_name=ol-web.us.archive.org&service=ol&kind=pageview&timediff=5.5&locale=en-US&referrer=-&loadtime=4494&nav_to_done_ms=8155&iaprop_fontSize=25.6px&iaprop_devicePixelRatio=1&version=2&count=14
script|8171|798|1361|https://openlibrary.org/static/build/js/search.DvIc4r-L.js
script|8171|797|1761|https://openlibrary.org/static/build/js/SearchFilterBar.gbZrK3nZ.js
script|8172|1090|864|https://openlibrary.org/static/build/js/dropper.BUS5vH2i.js
script|8173|1091|8059|https://openlibrary.org/static/build/js/my-books.7LXQlWaI.js
script|8173|1095|5450|https://openlibrary.org/static/build/js/jquery.colorbox.CZflEfcW.js
script|8173|1388|985|https://openlibrary.org/static/build/js/Toast.D2F2H6j-.js
link|8176|792|655|https://openlibrary.org/static/build/js/Toast.Crrs_-E6.css
script|8176|1386|1481|https://openlibrary.org/static/build/js/dialog.C-1J0-Zq.js
script|8180|1382|864|https://openlibrary.org/static/build/js/list_books.BKuxPel6.js
script|8180|1663|693|https://openlibrary.org/static/build/js/sort_options.-1Hdz3jc.js
script|8193|1650|891|https://openlibrary.org/static/build/js/hamburger-drawer.C5s-aRtw.js
beacon|8711|414|0|https://apollo.archive.org/matomo.php?action_name=search%20%7C%20Open%20Library&idsite=6&rec=1&r=797011&h=9&m=34&s=9&url=https%3A%2F%2Fopenlibrary.org%2Fsearch%3Fq%3Dperformance%2Bengineering&_id=&_idn=1&send_image=0&_refts=0&dimension1=visitor&pv_id=x2WytV&pf_net=537&pf_srv=3105&pf_tfr=11&pf_dm1=1955&pdf=1&qt=0&realp=0&wma=0&fla=0&java=0&ag=0&cookie=1&res=0x0
fetch|9585|316|336|https://openlibrary.org/partials/MyBooksDropperLists.json
fetch|249214|303|517|https://openlibrary.org/search.json?q=performance+engineering&limit=3&fields=key,title,author_name
fetch|249519|306|722|https://openlibrary.org/works/OL1904498W.json
fetch|249825|376|1432|https://openlibrary.org/works/OL1904498W/editions.json?limit=2"""

# Real response bodies captured in-session from the public OpenLibrary API.
BODIES = {
    "https://openlibrary.org/search.json?q=performance+engineering&limit=3&fields=key,title,author_name":
        '{"numFound":6121,"start":0,"numFoundExact":true,"num_found":6121,'
        '"documentation_url":"https://openlibrary.org/dev/docs/api/search",'
        '"q":"performance engineering","offset":null,"docs":['
        '{"author_name":["Dennis Moore"],"key":"/works/OL1904498W",'
        '"title":"Small-Block Chevy Marine Performance"},'
        '{"author_name":["Roger S. Pressman","Bruce Maxim"],"key":"/works/OL284009W",'
        '"title":"Software Engineering"},'
        '{"author_name":["Robert G. Cole"],"key":"/works/OL13506365W",'
        '"title":"Wide-area data network performance engineering"}]}',
    "https://openlibrary.org/works/OL1904498W.json":
        '{"title": "Small-Block Chevy Marine Performance", "covers": [1878858], '
        '"first_publish_date": "January 10, 2000", "key": "/works/OL1904498W", '
        '"authors": [{"type": {"key": "/type/author_role"}, "author": {"key": "/authors/OL227996A"}}], '
        '"type": {"key": "/type/work"}, "subjects": ["Maintenance and repair", "Marine engines"], '
        '"latest_revision": 5, "revision": 5, '
        '"created": {"type": "/type/datetime", "value": "2009-12-09T22:32:55.165173"}, '
        '"last_modified": {"type": "/type/datetime", "value": "2022-12-17T16:02:13.388699"}}',
    "https://openlibrary.org/works/OL1904498W/editions.json?limit=2":
        '{"links":{"self":"/works/OL1904498W/editions.json?limit=2",'
        '"work":"/works/OL1904498W"},"size":1,"entries":[{"publishers":["HP Trade"],'
        '"identifiers":{"goodreads":["3081202"]},"isbn_10":["1557883173"],"covers":[1878858],'
        '"physical_format":"Paperback","key":"/books/OL9394128M",'
        '"authors":[{"key":"/authors/OL227996A"}],"languages":[{"key":"/languages/eng"}],'
        '"title":"Small-Block Chevy Marine Performance","lccn":["99047390"],'
        '"number_of_pages":213,"isbn_13":["9781557883179"],'
        '"works":[{"key":"/works/OL1904498W"}],"type":{"key":"/type/edition"},'
        '"latest_revision":10,"revision":10,'
        '"created":{"type":"/type/datetime","value":"2008-04-30T09:38:13.731961"},'
        '"last_modified":{"type":"/type/datetime","value":"2022-12-17T16:02:13.388699"}}]}',
}

PHASE2_START = 249214      # real offset of the API journey
THINK_GAP_MS = 4000        # disclosed compression of the instrumentation gap


def parse() -> list[dict]:
    rows = []
    for line in LINES.strip().splitlines():
        t, st, d, s, url = line.split("|", 4)
        rows.append({"t": t, "st": int(st), "d": int(d), "s": int(s), "u": url})
    return rows


def main() -> None:
    rows = parse()
    (ROOT / "raw").mkdir(parents=True, exist_ok=True)
    (ROOT / "raw" / "app01_openlibrary.capture.json").write_text(
        json.dumps({"doc": "https://openlibrary.org/search?q=performance+engineering",
                    "rows": rows, "bodies": BODIES}, indent=1), encoding="utf-8")

    phase1_end = max(r["st"] + r["d"] for r in rows if r["st"] < PHASE2_START)
    entries = []
    for r in rows:
        st = r["st"] if r["st"] < PHASE2_START else (phase1_end + THINK_GAP_MS + (r["st"] - PHASE2_START))
        e = {"u": r["u"], "t": r["t"], "d": r["d"], "s": r["s"], "p": "h2", "st": st,
             "method": "GET", "status": 200,
             "mime": "application/json" if ".json" in r["u"] else None}
        if r["u"] in BODIES:
            e["body"] = BODIES[r["u"]]
        entries.append(e)
    entries.sort(key=lambda e: e["st"])
    # har_builder sequences by cumulative duration; feed it explicit gaps so real spacing survives
    for prev, cur in zip(entries, entries[1:]):
        prev["gap"] = max(0, cur["st"] - prev["st"] - prev["d"])

    out, n, hosts = write_har(
        {"entries": entries}, ROOT / "normalized" / "app01_openlibrary_search_to_work.har",
        app="OpenLibrary", domain="Library / public catalogue",
        flow="search books -> open work -> list editions",
        source="https://openlibrary.org (public, no login, HAR capture permitted)",
        notes=("REAL browser capture. HTML document body not retained. Inter-phase instrumentation gap "
               "compressed to 4s think time; intra-phase timings untouched. Duplicate probe runs dropped."))
    print(f"wrote {out.name}: {n} entries, {hosts} hosts")


if __name__ == "__main__":
    main()
