"""Parse job-alert emails into role records.

LinkedIn digests arrive as text/plain blocks separated by dashed lines.
Each block contains: title, company, location, optional tags, and a
``View job:`` URL.  LinkedIn URLs are kept only as an ID and a link for
the human to click; the code never requests them.

A generic fallback extracts job links and titles from other email formats.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class RoleRecord:
    title: str = ""
    company: str = ""
    location: str = ""
    url: str = ""
    source: str = ""
    source_id: str = ""
    description: str = ""


_LINKEDIN_ID_RE = re.compile(r"/jobs/view/(\d+)")

_LINKEDIN_URL_RE = re.compile(
    r"View job:\s*(https://www\.linkedin\.com/comm/jobs/view/\d+[^\s]*)",
    re.IGNORECASE,
)

_LINKEDIN_DASH_SEP = re.compile(r"\n-{30,}\n")

_TAG_LINES = {
    "this company is actively hiring",
    "apply with resume & profile",
    "see all jobs on linkedin:",
    "apply with resume and profile",
}

_TAG_STARTS = (
    "see all jobs",
    "manage your job alerts",
    "this email was intended",
    "learn why we",
    "stand out and let hirers",
    "you are receiving",
)

_GENERIC_URL_RE = re.compile(
    r'https?://[^\s<>"\']*jobs?[/?&][^\s<>"\']*(?:[?&][^\s<>"\']*)*',
    re.IGNORECASE,
)

_GENERIC_TITLE_RE = re.compile(
    r'(?:title|position|role)[:\s]*([^\n]+)',
    re.IGNORECASE,
)

_GENERIC_COMPANY_RE = re.compile(
    r'(?:company|employer|organization)[:\s]*([^\n]+)',
    re.IGNORECASE,
)


def parse_linkedin_digest(text: str) -> list[RoleRecord]:
    """Parse LinkedIn text/plain job-alert digest format.

    Jobs are separated by lines of dashes.  Each block has::

        Title
        Company
        Location
        [optional: This company is actively hiring]
        [optional: Apply with resume & profile]
        View job: https://www.linkedin.com/comm/jobs/view/12345/...

    Returns one RoleRecord per job block.
    """
    blocks = _LINKEDIN_DASH_SEP.split(text)
    records: list[RoleRecord] = []

    for block in blocks:
        lines = [line.strip() for line in block.split("\n") if line.strip()]
        if not lines:
            continue

        if lines[0].startswith("Your job alert"):
            lines = lines[1:]

        if not lines:
            continue

        title = lines[0] if len(lines) > 0 else ""
        company = lines[1] if len(lines) > 1 else ""

        location = ""
        url = ""
        skip = 0
        for i in range(2, len(lines)):
            line = lines[i]
            low = line.lower().strip("= ")
            if low in _TAG_LINES or low.startswith(_TAG_STARTS):
                skip += 1
                continue
            url_match = _LINKEDIN_URL_RE.search(line)
            if url_match:
                url = url_match.group(1)
                continue
            if i == 2 and not location:
                location = line
        if not title:
            continue

        id_match = _LINKEDIN_ID_RE.search(url) if url else None
        source_id = id_match.group(1) if id_match else ""

        if not source_id:
            continue

        records.append(RoleRecord(
            title=title,
            company=company,
            location=location,
            url=url,
            source="linkedin",
            source_id=source_id,
        ))

    return records


def _is_linkedin(text: str) -> bool:
    return "linkedin.com" in text.lower() or "linkedin" in text.lower()


def parse_generic(text: str) -> list[RoleRecord]:
    urls = _GENERIC_URL_RE.findall(text)
    if not urls:
        return []
    records: list[RoleRecord] = []
    for url in urls:
        title = ""
        company = ""
        for line in text.split("\n"):
            t = _GENERIC_TITLE_RE.search(line)
            if t:
                title = t.group(1).strip()
            c = _GENERIC_COMPANY_RE.search(line)
            if c:
                company = c.group(1).strip()
        records.append(RoleRecord(title=title, company=company, url=url, source="generic"))
    return records


def parse_alert(text: str, content_type: str = "text/plain") -> list[RoleRecord]:
    if _is_linkedin(text):
        records = []
        if "text/plain" in content_type:
            records = parse_linkedin_digest(text)
        if not records:
            records = parse_generic(text)
        return records
    return parse_generic(text)