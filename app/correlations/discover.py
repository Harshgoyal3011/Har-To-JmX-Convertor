from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from app.correlations.naming import derive_contextual_field_key
from app.models import CorrelationRule, SamplerModel
from app.patterns import (
    AUTHORIZATION_BEARER_RE,
    GUID_RE,
    HIDDEN_INPUT_RE,
    HTML_INPUT_RE,
    ID_FIELD_RE,
    TOKEN_NAME_RE,
    TOKEN_VALUE_RE,
    _SIMPLE_ID_VALUE_RE,
)
from app.utils import variable_name


@dataclass
class _ResponseValue:
    sampler_index: int
    sampler_name: str
    field_name: str
    value: str
    source: str
    extractor: str
    pattern: str
    json_key: str
    sibling_fields: dict = field(default_factory=dict)


def _looks_like_object_id(field_name: str, value: Any) -> bool:
    if not ID_FIELD_RE.search(field_name):
        return False
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return True
    if isinstance(value, str) and value.strip():
        return bool(_SIMPLE_ID_VALUE_RE.match(value.strip()))
    return False


def _is_dynamic_value(field_name: str, value: str) -> bool:
    if TOKEN_NAME_RE.search(field_name):
        return True
    if GUID_RE.search(value):
        return True
    if TOKEN_VALUE_RE.match(value) and len(value) >= 20:
        if re.match(r"^[A-Za-z][A-Za-z\s@.\-_']{3,}$", value):
            return False
        return True
    return False


def _inventory_response(index: int, sampler: SamplerModel) -> list[_ResponseValue]:
    found: list[_ResponseValue] = []

    def emit(
        field_name: str,
        value: str,
        source: str,
        extractor: str,
        pattern: str,
        json_key: str = "",
        min_length: int = 4,
        sibling_fields: dict | None = None,
    ) -> None:
        v = str(value if value is not None else "").strip()
        if not v or len(v) < min_length:
            return
        if v.lower() in {"true", "false", "null", "none", "undefined"}:
            return
        found.append(_ResponseValue(
            sampler_index=index,
            sampler_name=sampler.name,
            field_name=field_name,
            value=v,
            source=source,
            extractor=extractor,
            pattern=pattern,
            json_key=json_key or field_name,
            sibling_fields=sibling_fields or {},
        ))

    for header_name, header_val in sampler.response_headers:
        if not header_val:
            continue
        hl = header_name.lower()
        if hl == "set-cookie":
            cookie_name, _, rest = header_val.partition("=")
            cookie_value = rest.split(";", 1)[0].strip()
            if cookie_value:
                emit(
                    cookie_name, cookie_value,
                    source="set_cookie",
                    extractor="regex",
                    pattern=rf"{re.escape(cookie_name)}=([^;]+)",
                )
        elif hl in {"authorization", "x-auth-token", "x-access-token", "token"}:
            bearer_match = AUTHORIZATION_BEARER_RE.search(header_val)
            if bearer_match:
                emit(
                    "Authorization", bearer_match.group("token"),
                    source="response_header",
                    extractor="regex",
                    pattern=r"Bearer\s+([A-Za-z0-9\-_.=]+)",
                )
            elif TOKEN_VALUE_RE.match(header_val):
                emit(
                    header_name, header_val,
                    source="response_header",
                    extractor="regex",
                    pattern=rf"{re.escape(header_name)}:\s*(.+)",
                )
        elif TOKEN_NAME_RE.search(header_name) and header_val and TOKEN_VALUE_RE.match(header_val):
            emit(
                header_name, header_val,
                source="response_header",
                extractor="regex",
                pattern=rf"{re.escape(header_name)}:\s*(.+)",
            )

    text = sampler.response_text
    if not text:
        return found

    resp_mime = ""
    for hname, hval in sampler.response_headers:
        if hname.lower() == "content-type":
            resp_mime = hval.lower()
            break

    if "json" in resp_mime or text.lstrip().startswith(("{", "[")):
        try:
            body = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            body = None
        if body is not None:
            def _scan_json(obj: Any, ancestry: list[str]) -> None:
                if isinstance(obj, dict):
                    for k, v in obj.items():
                        path = ancestry + [k]
                        contextual_key = derive_contextual_field_key(k, ancestry, sampler.path, sampler.transaction)
                        full_json_path = ".".join(ancestry + [k]) if ancestry else k
                        if isinstance(v, str) and _is_dynamic_value(k, v):
                            emit(
                                contextual_key, v,
                                source="json_body",
                                extractor="json",
                                pattern=rf'"{re.escape(k)}"\s*:\s*"([^"]+)"',
                                json_key=full_json_path,
                            )
                        elif _looks_like_object_id(k, v):
                            if isinstance(v, (int, float)) and not isinstance(v, bool):
                                pattern = rf'"{re.escape(k)}"\s*:\s*(\d+(?:\.\d+)?)'
                            else:
                                pattern = rf'"{re.escape(k)}"\s*:\s*"([^"]+)"'
                            siblings = {
                                sib_k: sib_v for sib_k, sib_v in obj.items()
                                if sib_k != k and isinstance(sib_v, (str, int, float)) and not isinstance(sib_v, bool)
                            }
                            emit(
                                contextual_key, str(v),
                                source="json_body",
                                extractor="json",
                                pattern=pattern,
                                json_key=full_json_path,
                                min_length=1,
                                sibling_fields=siblings,
                            )
                        elif isinstance(v, (dict, list)):
                            _scan_json(v, path)
                elif isinstance(obj, list):
                    for item in obj[:25]:
                        _scan_json(item, ancestry)
            _scan_json(body, [])
    else:
        for match in HIDDEN_INPUT_RE.finditer(text):
            name, value = match.group("name"), match.group("value")
            if value:
                emit(name, value, source="html_hidden", extractor="css",
                     pattern=rf"name=[\"']{re.escape(name)}[\"'][^>]+value=[\"']([^\"']*)[\"']")
        for match in HTML_INPUT_RE.finditer(text):
            name, value = match.group("name"), match.group("value")
            if value:
                emit(name, value, source="html_input", extractor="css",
                     pattern=rf"name=[\"']{re.escape(name)}[\"'][^>]+value=[\"']([^\"']+)[\"']")

    return found


def _build_reverse_value_index(samplers: list[SamplerModel]) -> dict[str, list[int]]:
    index: dict[str, list[int]] = {}

    def _add(value: str, idx: int) -> None:
        if not value:
            return
        bucket = index.get(value)
        if bucket is None:
            index[value] = [idx]
        elif bucket[-1] != idx:
            bucket.append(idx)

    for i, sampler in enumerate(samplers):
        for _, v in sampler.query:
            _add(v, i)
        for _, v in sampler.post_params:
            _add(v, i)
        for _, v in sampler.cookies:
            _add(v, i)
        for seg in sampler.path.split("/"):
            if seg:
                _add(seg, i)
    return index


def _build_scan_texts(samplers: list[SamplerModel]) -> list[str]:
    texts: list[str] = []
    for sampler in samplers:
        parts = [sampler.post_body or ""]
        parts.extend(hv for _, hv in sampler.headers if hv)
        texts.append("\n".join(parts))
    return texts


def _find_consumers(
    value: str,
    producer_index: int,
    samplers: list[SamplerModel],
    reverse_index: dict[str, list[int]],
    scan_texts: list[str],
) -> list[str]:
    if not value:
        return []
    found_indices: set[int] = {idx for idx in reverse_index.get(value, []) if idx > producer_index}
    for idx in range(producer_index + 1, len(samplers)):
        if idx in found_indices:
            continue
        if value in scan_texts[idx]:
            found_indices.add(idx)
    return [samplers[idx].name for idx in sorted(found_indices)]


def classify_identifier(rv: _ResponseValue) -> str:
    if rv.source == "set_cookie":
        return "C"
    if TOKEN_NAME_RE.search(rv.field_name):
        return "D"
    if rv.source == "response_header" and rv.field_name.lower() == "authorization":
        return "D"
    if ID_FIELD_RE.search(rv.field_name):
        return "B"
    if GUID_RE.search(rv.value):
        return "E"
    return "B"


def discover_correlations(samplers: list[SamplerModel]) -> list[CorrelationRule]:
    inventory: list[_ResponseValue] = []
    for idx, sampler in enumerate(samplers):
        inventory.extend(_inventory_response(idx, sampler))

    reverse_index = _build_reverse_value_index(samplers)
    scan_texts = _build_scan_texts(samplers)
    rules: list[CorrelationRule] = []
    claimed_values: set[str] = set()

    for rv in inventory:
        if rv.value in claimed_values:
            continue
        consumers = _find_consumers(rv.value, rv.sampler_index, samplers, reverse_index, scan_texts)
        if not consumers:
            continue

        claimed_values.add(rv.value)
        classification = classify_identifier(rv)

        if rv.source == "set_cookie" and (TOKEN_NAME_RE.search(rv.field_name) or GUID_RE.search(rv.value)):
            confidence = "High"
            reason = f"Cookie '{rv.field_name}' set by server and consumed in later request - proven session/auth value"
        elif rv.source == "json_body" and TOKEN_NAME_RE.search(rv.field_name):
            confidence = "High"
            reason = f"JSON field '{rv.field_name}' returned by server and consumed in later request - token/session pattern confirmed"
        elif rv.source == "json_body" and ID_FIELD_RE.search(rv.field_name):
            confidence = "High"
            reason = (
                f"JSON field '{rv.field_name}' returned by the server and proven reused in "
                f"{len(consumers)} later request(s) - runtime object identifier, not user-entered"
            )
        elif rv.source in {"html_hidden", "html_input"} and TOKEN_NAME_RE.search(rv.field_name):
            confidence = "High"
            reason = f"Hidden HTML field '{rv.field_name}' generated by server and consumed in later request - anti-CSRF or ViewState pattern"
        elif rv.source == "response_header" and rv.field_name.lower() == "authorization":
            confidence = "High"
            reason = "Bearer token found in response header and consumed in later Authorization header"
        elif GUID_RE.search(rv.value):
            confidence = "Medium"
            reason = f"GUID-shaped value from '{rv.field_name}' in {rv.source} - server-generated ID proven to be reused"
        else:
            confidence = "Medium"
            reason = f"Value from '{rv.field_name}' ({rv.source}) proven to appear in a later request"

        producer_sampler = samplers[rv.sampler_index] if 0 <= rv.sampler_index < len(samplers) else None
        rules.append(CorrelationRule(
            variable=variable_name(rv.field_name),
            source_sampler=rv.sampler_name,
            pattern=rv.pattern,
            field="headers" if rv.source in {"set_cookie", "response_header"} else "body",
            value=rv.value,
            confidence=confidence,
            reason=reason,
            extractor=rv.extractor,
            json_key=rv.json_key,
            classification=classification,
            origin=f"{rv.source} on '{rv.sampler_name}'",
            consumers=tuple(consumers),
            sibling_fields=tuple(rv.sibling_fields.items()),
            producer_sampler_path=producer_sampler.path if producer_sampler else "",
            producer_method=producer_sampler.method if producer_sampler else "",
            producer_status=str(producer_sampler.status) if producer_sampler else "",
        ))

    for sampler in samplers:
        sampler.correlations = [r for r in rules if r.source_sampler == sampler.name]

    return rules
