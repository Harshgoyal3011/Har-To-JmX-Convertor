"""APP27-APP29 - REAL authentication workflows (Part 4 of the auth/MFA brief).

All captured live in the Claude browser pane. Credential disclosure:
  * quotes.toscrape.com is an explicit scraping-practice sandbox that accepts ANY credentials - there is
    no account behind it. Obviously-fake values (perftest/perftest) were used.
  * api.escuelajs.co and dummyjson.com publish their demo credentials in their own documentation as the
    intended public entry point; those exact values are used.
No real account was used, none was created, and no access control was bypassed.

Auth patterns covered: C/D form-urlencoded login, B email+password, A username+password, E JSON login,
F auth response token, G access token -> Authorization header, I refresh token -> next token request,
K/L CSRF / anti-forgery token.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_from_capture import build  # noqa: E402

BENCH = Path(__file__).resolve().parents[1]
S = "captured live via the Claude browser pane"

CSRF = "dVacEpRxvlUBjTtGKOJhqmbkIgDysQWYHorLZNzwMeiuXAfnPSCF"
LOGIN_HTML = (
 '<!DOCTYPE html>\n<html lang="en">\n<head>\n\t<meta charset="UTF-8">\n\t<title>Quotes to Scrape</title>\n'
 '    <link rel="stylesheet" href="/static/bootstrap.min.css">\n'
 '    <link rel="stylesheet" href="/static/main.css">\n</head>\n<body>\n    <div class="container">\n'
 '        <div class="row header-box">\n            <div class="col-md-8">\n                <h1>\n'
 '                    <a href="/" style="text-decoration: none">Quotes to Scrape</a>\n'
 '                </h1>\n            </div>\n            <div class="col-md-4">\n                <p>\n'
 '                    <a href="/login">Login</a>\n                </p>\n            </div>\n'
 '        </div>\n<body>\n    <form action="/login" method="post" accept-charset="utf-8" >\n'
 f'        <input type="hidden" name="csrf_token" value="{CSRF}"/>\n'
 '        <div class="row">\n            <div class="form-group col-xs-3">\n'
 '                <label for="username">Username</label>\n'
 '                <input type="text" class="form-control" id="username" name="username" />\n'
 '            </div>\n        </div>\n        <div class="row">\n'
 '            <div class="form-group col-xs-3">\n                <label for="username">Password</label>\n'
 '                <input type="password" class="form-control" id="password" name="password" />\n'
 '            </div>\n        </div>\n'
 '        <input type="submit" value="Login" class="btn btn-primary" />\n    </form>\n</body>\n'
 '    </div>\n</body>\n</html>')

PZ_ACCESS = ("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOjEsImlhdCI6MTc5MDIyODQxOSwiZXhwIjoxNzkxOTU2"
             "NDE5fQ.cWIU6d-5MADfM9esdKDtHHEJr0ni4h222HjirBmsfpE")
PZ_REFRESH = ("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOjEsImlhdCI6MTc5MDIyODQxOSwiZXhwIjoxNzkwMjY0"
              "NDE5fQ.vAuQ4ysR3EgWQ7Opo8cNW_bHbM4MN-fQYJMW9ovaXf4")

_DJ_HEAD = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
_DJ_BODY = ("eyJpZCI6MSwidXNlcm5hbWUiOiJlbWlseXMiLCJlbWFpbCI6ImVtaWx5LmpvaG5zb25AeC5kdW1teWpzb24uY29tIiwi"
            "Zmlyc3ROYW1lIjoiRW1pbHkiLCJsYXN0TmFtZSI6IkpvaG5zb24iLCJnZW5kZXIiOiJmZW1hbGUiLCJpbWFnZSI6Imh0"
            "dHBzOi8vZHVtbXlqc29uLmNvbS9pY29uL2VtaWx5cy8xMjgiLCJpYXQiOjE3OTAyMjg0M")
DJ_A1 = _DJ_HEAD + _DJ_BODY + "jAsImV4cCI6MTc5MDIzMDIyMH0.7MesqdjENv4iY7_rCi8tEdXcgbFaIx7hoHh17IcMp7Q"
DJ_R1 = _DJ_HEAD + _DJ_BODY + "jAsImV4cCI6MTc5MjgyMDQyMH0.JbxreBnwb5HqOpxnfW7eOt5gm6jCdMsvgAbuiwC6WV0"
DJ_A2 = _DJ_HEAD + _DJ_BODY + "jEsImV4cCI6MTc5MDIzMDIyMX0.Mnm-PzzY3prtVGegZXlgpww8u_FW8lHCj8xfJroAskQ"
DJ_R2 = _DJ_HEAD + _DJ_BODY + "jEsImV4cCI6MTc5MjgyMDQyMX0.zS__Ocq4NDT-yCopSfd0Zu5u6SQY8Xndu1MbJUaShnQ"


def A(u, st, d, b, m="GET", status=200, rb=None, mime=None, hdrs=None, rmime="application/json"):
    e = {"u": u, "st": st, "d": d, "status": status, "b": b, "method": m, "mime": rmime}
    if rb is not None:
        e["reqBody"] = rb
        e["reqMime"] = mime or "application/json"
    if hdrs:
        e["reqHeaders"] = hdrs
    return e


APPS = [
 ("app27_quotes_csrf_form_login.har", {
  "meta": {"app": "Quotes to Scrape", "domain": "Generic web / auth sandbox",
           "flow": "open login page -> submit the form-urlencoded login with its CSRF token",
           "source": "https://quotes.toscrape.com (public scraping sandbox, any credentials) - " + S,
           "provenance": "REAL_API_JOURNEY",
           "notes": "Anti-forgery token delivered as an HTML hidden input and posted back in a "
                    "form-urlencoded body. Fake credentials perfuser/Str0ngPass1; no real account exists."},
  "rows": [], "api": [
   A("https://quotes.toscrape.com/login", 1538, 299, LOGIN_HTML, rmime="text/html"),
   A("https://quotes.toscrape.com/login", 1837, 674,
     "<!DOCTYPE html>\n<html lang=\"en\"><head><title>Quotes to Scrape</title></head><body>ok</body></html>",
     m="POST", rmime="text/html",
     rb=f"csrf_token={CSRF}&username=perfuser&password=Str0ngPass1",
     mime="application/x-www-form-urlencoded")]}),

 ("app28_platzi_email_login_to_profile.har", {
  "meta": {"app": "Platzi Fake Store API", "domain": "E-commerce / SaaS",
           "flow": "email+password JSON login -> read own profile with the issued bearer token",
           "source": "https://api.escuelajs.co (public sandbox, documented demo user) - " + S,
           "provenance": "REAL_API_JOURNEY", "notes": "Consumer body shortened; producer complete."},
  "rows": [], "api": [
   A("https://api.escuelajs.co/api/v1/auth/login", 43376, 483,
     json.dumps({"access_token": PZ_ACCESS, "refresh_token": PZ_REFRESH}),
     m="POST", status=201, rb=json.dumps({"email": "john@mail.com", "password": "changeme"})),
   A("https://api.escuelajs.co/api/v1/auth/profile", 43859, 484,
     json.dumps({"id": 1, "email": "john@mail.com", "name": "Jhon", "role": "customer"}),
     hdrs=[{"name": "Authorization", "value": "Bearer " + PZ_ACCESS},
           {"name": "Accept", "value": "application/json"}])]}),

 ("app29_dummyjson_refresh_token_chain.har", {
  "meta": {"app": "DummyJSON", "domain": "SaaS / commerce API",
           "flow": "login -> exchange refresh token for a new access token -> authenticated profile call",
           "source": "https://dummyjson.com (public sandbox, documented test user) - " + S,
           "provenance": "REAL_API_JOURNEY",
           "notes": "Refresh-token chain. NOTE the first access token is superseded and never used "
                    "downstream - correlating it would be a false positive."},
  "rows": [], "api": [
   A("https://dummyjson.com/auth/login", 44343, 628,
     json.dumps({"accessToken": DJ_A1, "refreshToken": DJ_R1, "id": 1, "username": "emilys",
                 "email": "emily.johnson@x.dummyjson.com", "firstName": "Emily"}),
     m="POST", rb=json.dumps({"username": "emilys", "password": "emilyspass", "expiresInMins": 30})),
   A("https://dummyjson.com/auth/refresh", 44971, 591,
     json.dumps({"accessToken": DJ_A2, "refreshToken": DJ_R2}),
     m="POST", rb=json.dumps({"refreshToken": DJ_R1, "expiresInMins": 30})),
   A("https://dummyjson.com/auth/me", 45562, 595,
     json.dumps({"id": 1, "firstName": "Emily", "lastName": "Johnson", "username": "emilys"}),
     hdrs=[{"name": "Authorization", "value": "Bearer " + DJ_A2},
           {"name": "Accept", "value": "application/json"}])]}),
]

if __name__ == "__main__":
    (BENCH / "raw").mkdir(parents=True, exist_ok=True)
    for name, rec in APPS:
        (BENCH / "raw" / name.replace(".har", ".capture.json")).write_text(
            json.dumps(rec, indent=1), encoding="utf-8")
        out, n, hosts = build(rec, name)
        print(f"wrote {out.name}: {n} entries, {hosts} hosts")
