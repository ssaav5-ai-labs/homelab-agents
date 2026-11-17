"""Deterministic filters applied before LLM scoring.

Reads profile.md and filters roles by location/remote, seniority, exclusions,
and already-seen roles.
"""

from __future__ import annotations

import logging

from .parse import RoleRecord
from .vault import read_profile, read_roles

logger = logging.getLogger("job-search")

_LOCATION_KEYWORDS = {
    "dublin": ["dublin", "ireland", "dublin, ireland"],
    "ireland": ["ireland"],
    "hybrid dublin": ["dublin", "ireland", "dublin, ireland"],
    "uk": ["uk", "united kingdom", "london", "england", "scotland", "wales", "belfast"],
    "eu": [
        "europe", "eu", "berlin", "amsterdam", "paris", "barcelona", "madrid",
        "munich", "frankfurt", "stockholm", "copenhagen", "helsinki", "oslo",
        "vienna", "brussels", "lissabon", "lisbon", "milan", "rome", "warsaw",
    ],
    "emea": ["emea", "middle east", "africa", "dubai"],
}

_SENIORITY_MATCHES = {
    "director": ["director", "head of"],
    "head": ["head of"],
    "senior_manager": ["senior manager", "senior engineering manager", "senior sre manager"],
    "vp": ["vp", "vice president"],
}

_EXCLUDED_TITLES = {
    "graduate", "intern", "internship", "junior", "entry level",
    "entry-level", "associate", "technician", "support engineer",
    "help desk", "helpdesk", "customer service", "sales engineer",
    "account manager", "recruiter", "recruitment",
}


def _match_location(location_str: str, target_locations: list[str]) -> bool:
    low = location_str.lower()
    for target in target_locations:
        keywords = _LOCATION_KEYWORDS.get(target.lower(), [target.lower()])
        for kw in keywords:
            if kw in low:
                return True
    return False


def _match_seniority(title: str, target_seniority: list[str]) -> bool:
    low = title.lower()
    for level in target_seniority:
        matches = _SENIORITY_MATCHES.get(level.lower().replace(" ", "_"), [level.lower()])
        for m in matches:
            if m in low:
                return True
    return False


def _excluded_title(title: str) -> bool:
    low = title.lower()
    return any(e in low for e in _EXCLUDED_TITLES)


def _already_seen(source_id: str, existing_roles: list[dict]) -> bool:
    for role in existing_roles:
        if role.get("source_id") == source_id:
            return True
    return False


def apply_rules(roles: list[RoleRecord]) -> tuple[list[RoleRecord], list[str]]:
    profile = read_profile()
    target_locations = profile.get("target_locations", [])
    target_seniority = profile.get("target_seniority", [])
    exclude_companies = [c.lower() for c in profile.get("exclude_companies", [])]
    existing = read_roles()

    passed: list[RoleRecord] = []
    skipped: list[str] = []

    for role in roles:
        skip_reason = None

        if _already_seen(role.source_id, existing):
            skip_reason = f"seen: {role.source_id}"
        elif _excluded_title(role.title):
            skip_reason = f"excluded title: {role.title}"
        elif role.company.lower() in exclude_companies:
            skip_reason = f"excluded company: {role.company}"
        elif (
            target_locations
            and role.location
            and not _match_location(role.location, target_locations)
        ):
            skip_reason = f"location: {role.location}"
        elif target_seniority and not _match_seniority(role.title, target_seniority):
            skip_reason = f"seniority: {role.title}"

        if skip_reason:
            skipped.append(f"SKIP {role.title} at {role.company}: {skip_reason}")
        else:
            passed.append(role)

    return passed, skipped