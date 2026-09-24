"""SYNTHETIC_MFA - NOT REAL-WORLD BENCHMARK.

This fixture is INVENTED. No such capture exists and no real application was involved. It exists solely
to exercise engine behaviour on an MFA shape that no public sandbox exposes (see AUTH_MFA_REPORT.md:
real MFA is BLOCKED because it needs either a real second factor or a self-hosted IdP where an account
must be created).

It is stamped provenance = SYNTHETIC_MFA so the baseline runner buckets it separately, and it is
EXCLUDED from every real-application recall/precision figure.

Expected behaviour:
    username / password   -> PARAMETERIZE  (user input)
    otp                   -> PARAMETERIZE  (entered by the tester; dynamic but NOT server-generated)
    challengeId           -> CORRELATE     (server-issued, consumed by the verify step)
    accessToken           -> CORRELATE     (server-issued after MFA, consumed by the business call)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_from_capture import build  # noqa: E402

BENCH = Path(__file__).resolve().parents[1]
CHALLENGE = "CHL-8f2a9d3e7b61"
TOKEN = ("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJwZXJmdXNlciIsIm1mYSI6dHJ1ZSwiaWF0IjoxNzkw"
         "MjI4NDE5fQ.q7Rm2XbN4pLtVyCeZa1Ws9KdHgUjFoI3xMnBvQrTiAY")

RECORD = {
 "meta": {"app": "SYNTHETIC_MFA fixture", "domain": "SYNTHETIC - not a real application",
          "flow": "login -> MFA challenge -> OTP verification -> authenticated business call",
          "source": "SYNTHETIC_MFA - NOT REAL-WORLD BENCHMARK (invented, no capture exists)",
          "provenance": "SYNTHETIC_MFA",
          "notes": "Excluded from all real-application precision/recall figures."},
 "rows": [],
 "api": [
  {"u": "https://mfa.example.com/api/login", "method": "POST", "st": 0, "d": 240, "status": 200,
   "reqBody": json.dumps({"username": "perfuser", "password": "Str0ngPass1"}),
   "reqMime": "application/json",
   "b": json.dumps({"mfaRequired": True, "challengeId": CHALLENGE, "channel": "totp",
                    "expiresIn": 300})},
  {"u": "https://mfa.example.com/api/mfa/verify", "method": "POST", "st": 4300, "d": 260,
   "status": 200,
   "reqBody": json.dumps({"challengeId": CHALLENGE, "otp": "482913"}),
   "reqMime": "application/json",
   "b": json.dumps({"accessToken": TOKEN, "tokenType": "Bearer", "expiresIn": 1800})},
  {"u": "https://mfa.example.com/api/account/summary", "method": "GET", "st": 8600, "d": 210,
   "status": 200,
   "reqHeaders": [{"name": "Authorization", "value": "Bearer " + TOKEN},
                  {"name": "Accept", "value": "application/json"}],
   "b": json.dumps({"accountId": "ACC-44120", "balance": 1284.55, "currency": "EUR"})},
 ],
}

if __name__ == "__main__":
    (BENCH / "raw").mkdir(parents=True, exist_ok=True)
    (BENCH / "raw" / "SYNTHETIC_MFA.capture.json").write_text(json.dumps(RECORD, indent=1),
                                                              encoding="utf-8")
    out, n, hosts = build(RECORD, "SYNTHETIC_MFA_challenge_otp.har")
    print(f"wrote {out.name}: {n} entries, {hosts} hosts  [SYNTHETIC_MFA - NOT REAL-WORLD BENCHMARK]")
