from __future__ import annotations

import json
import re

from app.models import Parameter, SamplerModel
from app.patterns import (
    EMAIL_VALUE_RE,
    ENTERPRISE_APP_RULES,
    GUID_RE,
    TOKEN_NAME_RE,
    TOKEN_VALUE_RE,
    USER_DATA_RE,
)
from app.utils import variable_name


def detect_enterprise_apps(samplers: list[SamplerModel]) -> list[str]:
    domains = " ".join(sorted({s.domain for s in samplers if s.domain}))
    found: list[str] = []
    for pattern, label in ENTERPRISE_APP_RULES:
        if pattern.search(domains) and label not in found:
            found.append(label)
    return found


def discover_parameters(samplers: list[SamplerModel]) -> list[Parameter]:
    candidates: dict[str, dict] = {}

    for sampler in samplers:
        if sampler.method in {"POST", "PUT", "PATCH"}:
            for name, value in sampler.post_params:
                _consider_param(name, value, "form body", sampler.name, candidates)
            if sampler.post_body and ("json" in (sampler.mime_type or "").lower() or sampler.post_body.lstrip().startswith("{")):
                try:
                    body = json.loads(sampler.post_body)
                    if isinstance(body, dict):
                        for k, v in body.items():
                            if isinstance(v, str):
                                _consider_param(k, v, "json body", sampler.name, candidates)
                except (json.JSONDecodeError, ValueError):
                    pass

        for name, value in sampler.query:
            _consider_param(name, value, "query string", sampler.name, candidates)

    parameters: list[Parameter] = []
    for var_name, meta in candidates.items():
        parameters.append(Parameter(
            name=var_name,
            value=meta["value"],
            occurrences=meta["occurrences"],
            reason=", ".join(sorted(meta["locations"])),
            confidence=meta["confidence"],
            csv_bound=True,
            source_samplers=frozenset(meta["samplers"]),
        ))
    return sorted(parameters, key=lambda p: (-p.occurrences, p.name))


def _consider_param(name: str, value: str, location: str, sampler_name: str, candidates: dict) -> None:
    if not name or not value:
        return
    value = str(value).strip()
    if not value or len(value) > 200:
        return

    if GUID_RE.search(value):
        return
    if TOKEN_VALUE_RE.match(value) and len(value) >= 24:
        return
    if re.match(r"^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$", value):
        return
    if len(value) < 3:
        return
    if value.lower() in {"true", "false", "null", "undefined", "none", "0", "1"}:
        return

    if not USER_DATA_RE.search(name):
        return

    if TOKEN_NAME_RE.search(name):
        return

    var_name = variable_name(name)
    if var_name not in candidates:
        is_email = bool(EMAIL_VALUE_RE.match(value))
        candidates[var_name] = {
            "value": value,
            "occurrences": 0,
            "samplers": set(),
            "locations": set(),
            "confidence": "High" if is_email else "High" if USER_DATA_RE.search(name) else "Medium",
        }
    candidates[var_name]["occurrences"] += 1
    candidates[var_name]["samplers"].add(sampler_name)
    candidates[var_name]["locations"].add(location)
