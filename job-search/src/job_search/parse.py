"""Parse job-alert emails into role records.

A LinkedIn parser for its alert HTML, a generic fallback that extracts job
links and titles, and a ``fast`` fallback only when both find nothing.
LinkedIn links are kept only as an ID and a link for the human to click;
the code never requests them.
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


_LINKEDIN_JOB_RE = re.compile(
    r'<a[^>]*href="(https://www\.linkedin\.com/jobs/view/[^"]*)"[^>]*>'
    r'\s*(.*?)\s*</a>',
    re.DOTALL,
)

_LINKEDIN_ID_RE = re.compile(r"/jobs/view/(\d+)")

_LINKEDIN_TITLE_RE = re.compile(r'<h3[^>]*>\s*(.*?)\s*</h3>', re.DOTALL)

_LINKEDIN_COMPANY_RE = re.compile(
    r'(?:company|at)\s*</[^>]*>\s*<[^>]*>\s*(.*?)\s*<',
    re.DOTALL | re.IGNORECASE,
)

_LINKEDIN_LOCATION_RE = re.compile(
    r'(?:location|in)\s*</[^>]*>\s*<[^>]*>\s*(.*?)\s*<',
    re.DOTALL | re.IGNORECASE,
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


def parse_linkedin_alert(html: str) -> list[RoleRecord]:
    records: list[RoleRecord] = []
    for match in _LINKEDIN_JOB_RE.finditer(html):
        url = match.group(1)
        snippet = match.group(2).strip()
        id_match = _LINKEDIN_ID_RE.search(url)
        source_id = id_match.group(1) if id_match else ""

        title_match = _LINKEDIN_TITLE_RE.search(snippet)
        title = title_match.group(1).strip() if title_match else ""

        company_match = re.search(r'\b([A-Z][A-Za-z0-9 .&]+?)\s*(?:<|$)', snippet)
        company = company_match.group(1).strip() if company_match else ""

        records.append(RoleRecord(
            title=title,
            company=company,
            url=url,
            source="linkedin",
            source_id=source_id,
        ))
    return records


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


def parse_alert(text: str) -> list[RoleRecord]:
    records = parse_linkedin_alert(text) or parse_generic(text)
    if records:
        return records

    return []