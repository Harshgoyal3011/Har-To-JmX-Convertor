"""Set-Cookie value boundaries shared by generation and verification.

RFC 6265 cookie-octet excludes whitespace, controls, quote, comma, semicolon
and backslash. Quoted values use the same octets; quotes are wire delimiters.
Cookie names are case-sensitive; the HTTP header name is case-insensitive.
"""

from __future__ import annotations

import re

_OCTETS = r"\x21\x23-\x2B\x2D-\x3A\x3C-\x5B\x5D-\x7E"


def cookie_value_expression(name: str) -> str:
    # Retain quote delimiters in group 1, preserving the recorded wire value.
    # Both alternatives are bounded; a next header/attribute cannot be consumed.
    value = rf'("[{_OCTETS}]*"|[{_OCTETS}]+)'
    # JMeter 5.x uses Apache ORO, which has no scoped (?i:...) modifier.
    header = "[Ss][Ee][Tt]-[Cc][Oo][Oo][Kk][Ii][Ee]"
    return (
        rf"(?m)^{header}:[ \t]*{re.escape(name)}[ \t]*=[ \t]*{value}"
        rf"(?=[ \t]*(?:;|\r?$))"
    )
