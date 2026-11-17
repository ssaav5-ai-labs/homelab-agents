"""Fetch full job descriptions from public ATS APIs.

Supports Greenhouse, Lever and Ashby. Any other host is refused. LinkedIn
URLs return a refusal message.
"""

from __future__ import annotations

import logging
from urllib.parse import urlparse

import requests

logger = logging.getLogger("job-search")

ALLOWED_HOSTS = {
    "boards-api.greenhouse.io",
    "api.lever.co",
    "api.ashbyhq.com",
}

_TIMEOUT = 20
_MAX_BYTES = 1_048_576

BANNED_DOMAINS = {"linkedin.com", "www.linkedin.com"}


class AtsError(Exception):
    pass


def fetch_description(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.hostname or ""

    for domain in BANNED_DOMAINS:
        if host == domain or host.endswith(f".{domain}"):
            return (
                "LinkedIn links can't be fetched: "
                "paste the ad's text, or the employer's own job link"
            )

    if host not in ALLOWED_HOSTS:
        raise AtsError(f"host {host} is not an allowed ATS API")

    try:
        resp = requests.get(url, timeout=_TIMEOUT, stream=True)
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise AtsError(f"ATS request failed: {exc}") from exc

    content_length = resp.headers.get("content-length")
    if content_length and int(content_length) > _MAX_BYTES:
        raise AtsError(f"response too large: {content_length} bytes")

    chunks: list[bytes] = []
    total = 0
    for chunk in resp.iter_content(chunk_size=8192):
        chunks.append(chunk)
        total += len(chunk)
        if total > _MAX_BYTES:
            raise AtsError(f"response exceeded {_MAX_BYTES} byte cap")

    return b"".join(chunks).decode("utf-8", errors="replace")


def extract_text_from_json(data: dict, source: str) -> str:
    if source == "greenhouse":
        return data.get("content", "")
    if source == "lever":
        parts = []
        for section in data.get("sections", []):
            parts.append(section.get("text", ""))
        return "\n\n".join(parts)
    if source == "ashby":
        return data.get("descriptionHtml", "") or data.get("description", "")
    return str(data)