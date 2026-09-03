from __future__ import annotations

import re
from urllib.parse import unquote


def clean_name(value: str, fallback: str = "Transaction") -> str:
    value = unquote(value or "").strip()
    value = re.sub(r"https?://", "", value)
    value = re.sub(r"[^A-Za-z0-9 _./:-]+", " ", value)
    value = re.sub(r"\s+", " ", value).strip(" /")
    return value[:90] or fallback


def variable_name(name: str) -> str:
    name = re.sub(r"[^A-Za-z0-9_]+", "_", name.strip())
    name = re.sub(r"_+", "_", name).strip("_")
    if not name:
        name = "value"
    if name[0].isdigit():
        name = f"v_{name}"
    return name[:48]


def xml_safe_comment_text(text: str) -> str:
    return re.sub(r"-{2,}", " - ", text).rstrip("-")
