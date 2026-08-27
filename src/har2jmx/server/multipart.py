from __future__ import annotations

import re
from email.parser import BytesParser
from email.policy import default
from typing import Any


def parse_multipart(headers: Any, body: bytes) -> tuple[bytes, dict[str, str]]:
    content_type = headers.get("Content-Type", "")
    message = BytesParser(policy=default).parsebytes(
        f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode() + body
    )
    fields: dict[str, str] = {}
    file_bytes: bytes | None = None
    for part in message.iter_parts():
        disposition = part.get("Content-Disposition", "")
        if not disposition:
            continue
        name_match = re.search(r'name="(?P<name>[^"]+)"', disposition)
        if not name_match:
            continue
        name = name_match.group("name")
        payload = part.get_payload(decode=True) or b""
        if name == "harfile":
            file_bytes = payload
            continue
        fields[name] = payload.decode(part.get_content_charset("utf-8"), errors="replace").strip()
    if file_bytes is None:
        raise ValueError("Upload a HAR file using the file picker.")
    return file_bytes, fields
