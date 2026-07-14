from __future__ import annotations

import re
from urllib.parse import unquote

from app.models import CorrelationRule, Parameter


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


def apply_variable(value: str, parameters: list[Parameter], correlations: list[CorrelationRule]) -> str:
    if value is None:
        return ""
    replaced = str(value)
    all_vars = [(p.name, p.value) for p in parameters if p.value] + [(c.variable, c.value) for c in correlations if c.value]
    for name, raw in all_vars:
        if raw == replaced:
            return f"${{{name}}}"
        if len(raw) >= 8 and raw in replaced:
            replaced = replaced.replace(raw, f"${{{name}}}")
    return replaced


def xml_safe_comment_text(text: str) -> str:
    return re.sub(r"-{2,}", " - ", text).rstrip("-")
