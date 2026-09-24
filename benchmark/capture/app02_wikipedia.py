"""APP02 - Wikipedia (Knowledge / media). REAL browser capture on en.wikipedia.org.

Journey: search articles -> open article info+categories by pageid -> fetch article extract by pageid.
Genuine dependency: the search response returns pageid 6615610, which the next TWO requests consume as
`pageids=6615610` (a NUMERIC id in a query parameter — a different correlation shape from APP01's
path-style key). Real timings preserved; the ~11s gap between page load and the API journey is genuine
interactive think time and is NOT compressed.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_from_capture import build  # noqa: E402

BENCH = Path(__file__).resolve().parents[1]

ROWS = """navigation|0|1640|25926|https://en.wikipedia.org/wiki/Performance_engineering
link|1126|108|25090|https://en.wikipedia.org/w/load.php?lang=en&modules=ext.cite.parsoid.styles%7Cext.cite.styles%7Cext.uls.interlanguage&only=styles&skin=vector-2022
link|1126|81|2599|https://en.wikipedia.org/w/load.php?lang=en&modules=site.styles&only=styles&skin=vector-2022
img|1126|183|44392|https://en.wikipedia.org/static/images/icons/enwiki-25.svg
script|1126|126|22237|https://en.wikipedia.org/w/load.php?lang=en&modules=startup&only=scripts&raw=1&skin=vector-2022
img|1126|143|5088|https://en.wikipedia.org/static/images/mobile/copyright/wikipedia-tagline-en-25.svg
img|1126|147|4320|https://en.wikipedia.org/static/images/mobile/copyright/wikipedia-wordmark-en-25.svg
css|1241|70|487|https://en.wikipedia.org/w/load.php?modules=skins.vector.icons&image=menu&format=original&lang=en&skin=vector-2022&version=1d1j6
css|1242|74|532|https://en.wikipedia.org/w/load.php?modules=skins.vector.icons&image=search&format=original&lang=en&skin=vector-2022&version=1d1j6
css|1242|73|518|https://en.wikipedia.org/w/load.php?modules=skins.vector.icons&image=userAvatar&format=original&lang=en&skin=vector-2022&version=1d1j6
css|1243|73|576|https://en.wikipedia.org/w/load.php?modules=skins.vector.icons&image=heart&format=original&lang=en&skin=vector-2022&version=1d1j6
css|1243|73|540|https://en.wikipedia.org/w/load.php?modules=skins.vector.icons&image=logIn&format=original&lang=en&skin=vector-2022&version=1d1j6
css|1243|74|503|https://en.wikipedia.org/w/load.php?modules=skins.vector.icons&image=listBullet&format=original&lang=en&skin=vector-2022&version=1d1j6
css|1246|74|748|https://en.wikipedia.org/w/load.php?modules=skins.vector.icons&image=language&variant=progressive&format=original&lang=en&skin=vector-2022&version=1d1j6
css|1246|77|493|https://en.wikipedia.org/w/skins/Vector/resources/skins.vector.styles/images/arrow-down-progressive.svg?5cd6d
css|1247|79|503|https://en.wikipedia.org/w/load.php?modules=skins.vector.icons&image=verticalEllipsis&format=original&lang=en&skin=vector-2022&version=1d1j6
css|1247|85|584|https://en.wikipedia.org/w/load.php?modules=skins.vector.icons&image=eye&format=original&lang=en&skin=vector-2022&version=1d1j6
css|1250|83|541|https://en.wikipedia.org/w/skins/Vector/resources/skins.vector.styles/images/link-external-small-ltr-progressive.svg?fb64d
css|1250|226|525|https://upload.wikimedia.org/wikipedia/commons/4/4d/Icon_pdf_file.png
script|1457|72|7404|https://en.wikipedia.org/w/load.php?lang=en&modules=ext.gadget.ReferenceTooltips%2Cswitcher&skin=vector-2022&version=t9fd4
script|1458|82|17777|https://en.wikipedia.org/w/load.php?lang=en&modules=ext.visualEditor.core.utils.parsing&skin=vector-2022&version=1yc9z
script|1459|165|205243|https://en.wikipedia.org/w/load.php?lang=en&modules=ext.centralNotice.bannerHistoryLogger%2CchoiceData%2Cdisplay%2CgeoIP%7Cext.eventLogging%2CnavigationTiming%2Cpopups%2CwikimediaEvents&skin=vector-2022&version=uwgzn
script|1695|72|26026|https://en.wikipedia.org/w/load.php?lang=en&modules=ext.cite.referencePreviews%7Cext.popups.main&skin=vector-2022&version=j4tat
script|1699|69|2127|https://en.wikipedia.org/w/load.php?lang=en&modules=mw.config.values.wbCurrentSiteDetails%2CwbRepo&skin=vector-2022&version=1z0vv
beacon|1732|388|300|https://en.wikipedia.org/ins-502b/v2/events?hasty=true"""

SEARCH_BODY = json.dumps({
    "batchcomplete": "", "continue": {"sroffset": 2, "continue": "-||"},
    "query": {"searchinfo": {"totalhits": 52396}, "search": [
        {"ns": 0, "title": "Performance engineering", "pageid": 6615610, "size": 14757,
         "wordcount": 1701, "timestamp": "2026-07-09T19:06:23Z"},
        {"ns": 0, "title": "Hennessey Performance Engineering", "pageid": 35920450, "size": 20033,
         "wordcount": 2062, "timestamp": "2026-09-07T05:55:51Z"}]}})

INFO_BODY = json.dumps({
    "continue": {"clcontinue": "6615610|Articles_needing_additional_references_from_March_2009",
                 "continue": "||info"},
    "query": {"pages": {"6615610": {
        "pageid": 6615610, "ns": 0, "title": "Performance engineering", "contentmodel": "wikitext",
        "pagelanguage": "en", "touched": "2026-09-23T05:02:41Z", "lastrevid": 1363364321,
        "length": 14757, "categories": [
            {"ns": 14, "title": "Category:All articles needing additional references"},
            {"ns": 14, "title": "Category:All articles with style issues"}]}}}})

EXTRACT_BODY = json.dumps({
    "batchcomplete": "", "query": {"pages": {"6615610": {
        "pageid": 6615610, "ns": 0, "title": "Performance engineering",
        "extract": ("Performance engineering encompasses the techniques applied during a systems "
                    "development life cycle to ensure the non-functional requirements for "
                    "performance (such as throughput, latency, or memory usage) will be met.")}}}})

RECORD = {
    "meta": {
        "app": "Wikipedia", "domain": "Knowledge / media",
        "flow": "search articles -> article info by pageid -> article extract by pageid",
        "source": "https://en.wikipedia.org (public, no login, MediaWiki API)",
        "notes": ("REAL browser capture. HTML document body not retained. API response bodies are real "
                  "but truncated to the fields observed. Real timings preserved (no gap compression)."),
    },
    "rows": ROWS.strip().splitlines(),
    "api": [
        {"u": "https://en.wikipedia.org/w/api.php?action=query&list=search&srsearch=performance%20engineering&srlimit=2&format=json",
         "st": 13128, "d": 588, "status": 200, "b": SEARCH_BODY},
        {"u": "https://en.wikipedia.org/w/api.php?action=query&pageids=6615610&prop=info|categories&cllimit=2&format=json",
         "st": 13716, "d": 475, "status": 200, "b": INFO_BODY},
        {"u": "https://en.wikipedia.org/w/api.php?action=query&pageids=6615610&prop=extracts&exintro=1&explaintext=1&format=json",
         "st": 14190, "d": 450, "status": 200, "b": EXTRACT_BODY},
    ],
}

if __name__ == "__main__":
    (BENCH / "raw").mkdir(parents=True, exist_ok=True)
    (BENCH / "raw" / "app02_wikipedia.capture.json").write_text(
        json.dumps(RECORD, indent=1), encoding="utf-8")
    out, n, hosts = build(RECORD, "app02_wikipedia_search_to_article.har")
    print(f"wrote {out.name}: {n} entries, {hosts} hosts")
