"""The job-search MCP server: read-only scoring, drafting with approval hints.

Streamable HTTP on 0.0.0.0:8000/mcp, bearer ``JOBS_MCP_TOKEN``, one draft at
a time. Tools with ``readOnlyHint: false`` (draft, set_status) prompt Hermes
for ``Allow once``.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import secrets
import time
import unicodedata
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from .ats import fetch_description
from .draft import draft_application as _draft_application
from .score import score_role as _score_role
from .vault import (
    read_digest,
    read_roles,
    update_role_status,
    write_draft_and_role,
)

logger = logging.getLogger("job-search")

TOKEN = os.environ["JOBS_MCP_TOKEN"]

mcp = FastMCP(
    "job-search",
    host="0.0.0.0",
    port=8000,
    streamable_http_path="/mcp",
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[
            "job-search.career.svc:8000",
            "job-search.career.svc.cluster.local:8000",
        ],
    ),
)

READ_ONLY = ToolAnnotations(readOnlyHint=True)
WRITE_TOOL = ToolAnnotations(readOnlyHint=False, destructiveHint=False)

_busy = asyncio.Lock()


async def _run_guarded(name: str, fn: Any) -> str:
    if _busy.locked():
        logger.info("call=%s outcome=busy", name)
        return "busy, try again in a few minutes"
    await _busy.acquire()
    start = time.monotonic()
    try:
        result = await fn() if asyncio.iscoroutinefunction(fn) else await asyncio.to_thread(fn)
        logger.info("call=%s duration=%.1fs outcome=ok", name, time.monotonic() - start)
        return result
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "call=%s duration=%.1fs outcome=error error=%s",
            name,
            time.monotonic() - start,
            exc,
        )
        return f"error: {exc}"
    finally:
        _busy.release()


def _resolve_ad_text(text_or_url: str) -> str:
    text_or_url = text_or_url.strip()
    if text_or_url.startswith(("http://", "https://")):
        try:
            return fetch_description(text_or_url)
        except Exception as exc:
            return f"could not fetch description: {exc}"
    return text_or_url


_SLUG_MAX = 60
_ROLE_DESC_CAP = 12_000


def _normalize_text(text: str) -> str:
    return " ".join(text.split()).strip().lower()


def _slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii", "ignore")
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def _clean_field(value: str) -> str:
    value = re.sub(r"^\s*#{1,6}\s*", "", value)
    value = re.sub(r"^\s*(?:[-*]|\d+[.)])\s*", "", value)
    return value.strip()


def _company_from_url(url: str) -> str:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    parts = [p for p in parsed.path.split("/") if p]
    if host == "boards-api.greenhouse.io" and len(parts) >= 3 and parts[1] == "boards":
        return parts[2]
    if host == "api.lever.co" and len(parts) >= 3 and parts[1] == "postings":
        return parts[2]
    if host == "api.ashbyhq.com" and "job-board" in parts:
        idx = parts.index("job-board")
        if idx + 1 < len(parts):
            return parts[idx + 1]
    return ""


def _classify_url(url: str) -> tuple[str, str]:
    """Return ``(source, source_id)`` for an ATS URL, or ``("", "")``."""
    if not url:
        return "", ""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    parts = [p for p in parsed.path.split("/") if p]
    if host == "boards-api.greenhouse.io":
        return "greenhouse", parts[-1] if parts else ""
    if host == "api.lever.co":
        return "lever", parts[-1] if parts else ""
    if host == "api.ashbyhq.com":
        return "ashby", parts[-1] if parts else ""
    return host, ""


def _extract_company_title(ad_text: str, url: str = "") -> tuple[str, str]:
    """Best-effort company/title extraction from an ad (or its URL)."""
    company = title = ""
    lines = [ln.strip() for ln in ad_text.splitlines() if ln.strip()]

    for ln in lines:
        m = re.search(r"\b(?:title|position|role)\s*:\s*(.{1,120})$", ln, re.IGNORECASE)
        if m and not title:
            title = m.group(1).strip()
        m = re.search(
            r"\b(?:company|employer|organization|organisation)\s*:\s*(.{1,120})$",
            ln,
            re.IGNORECASE,
        )
        if m and not company:
            company = m.group(1).strip()
    if company and title:
        return _clean_field(company), _clean_field(title)

    for ln in lines[:10]:
        m = re.match(r"^(.{3,120}?)\s+(?:at|@)\s+([A-Za-z0-9][\w&.,'() -]{1,60})$", ln)
        if m:
            return _clean_field(m.group(2)), _clean_field(m.group(1))

    if not title and lines and len(lines[0]) <= 120:
        first = lines[0].lower()
        if not first.startswith(
            ("http", "about ", "the role", "job description", "role description")
        ):
            title = lines[0]

    if not company and url:
        company = _company_from_url(url)

    return _clean_field(company), _clean_field(title)


def _resolve_company_title(
    ad_text: str, url: str, company: str = "", title: str = ""
) -> tuple[str, str]:
    """Resolve company/title: explicit params first, then heuristics, else empty."""
    if not company or not title:
        extracted_company, extracted_title = _extract_company_title(ad_text, url)
        company = company or extracted_company
        title = title or extracted_title
    return company, title


def derive_role_id(ad_text: str, url: str = "", company: str = "", title: str = "") -> str:
    """Derive a stable, filesystem-safe role ID: ``<company>-<title>`` slug
    (max 60 chars) plus an 8-char hash of the normalized text."""
    company, title = _resolve_company_title(ad_text, url, company, title)
    slug = _slugify(f"{company} {title}").strip("-")
    slug = slug[:_SLUG_MAX].strip("-")
    digest = hashlib.blake2b(_normalize_text(ad_text).encode(), digest_size=4).hexdigest()
    return f"{slug}-{digest}" if slug else digest


def _q(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


@mcp.tool(annotations=READ_ONLY)
async def score_role(text_or_url: str) -> str:
    """Score a role against the profile. Accepts ad text or a public ATS job URL.

    Returns a JSON card with score, why, gaps, and must_ask.
    """
    return await _run_guarded(
        "score_role",
        lambda: _score_result(text_or_url),
    )


def _score_result(text_or_url: str) -> str:
    ad = _resolve_ad_text(text_or_url)
    if ad.startswith("could not fetch") or ad.startswith("LinkedIn links cannot"):
        return ad
    result = _score_role(ad)
    url = text_or_url.strip() if text_or_url.strip().startswith(("http://", "https://")) else ""
    company, title = _extract_company_title(ad, url)
    result["company"] = company
    result["title"] = title
    return json.dumps(result)


@mcp.tool(annotations=READ_ONLY)
async def todays_matches() -> str:
    """Return today's job digest, or the most recent one."""
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    content = read_digest(today)
    if content:
        return content
    return "no digest for today"


@mcp.tool(annotations=READ_ONLY)
async def pipeline_summary() -> str:
    """Return a summary of all roles by status, with next actions overdue."""
    roles = read_roles()
    if not roles:
        return "pipeline empty"

    by_status: dict[str, list[dict]] = {}
    overdue: list[dict] = []
    today = datetime.now(UTC).date()

    for role in roles:
        status = role.get("status", "unknown")
        by_status.setdefault(status, []).append(role)
        next_date = role.get("next_action_date")
        if next_date and next_date < today:
            overdue.append(role)

    lines = []
    for status, status_roles in sorted(by_status.items()):
        lines.append(f"{status}: {len(status_roles)}")

    if overdue:
        lines.append(f"\nOverdue follow-ups ({len(overdue)}):")
        for role in overdue[:10]:
            lines.append(
                f"  - {role.get('title', '?')} at {role.get('company', '?')} "
                f"(since {role.get('next_action_date', '?')})"
            )

    return "\n".join(lines)


@mcp.tool(annotations=WRITE_TOOL)
async def draft_application(
    role_id_or_text: str,
    company: str = "",
    title: str = "",
    score: int = 0,
) -> str:
    """Draft a CV summary and cover note for a role. Accepts ad text or a role ID.

    Optionally pass company, title and score (e.g. from a score_role result) so
    the role ID and stored score are exact; otherwise they are derived from the
    ad and fall back to "unknown"/0.
    Writes career-vault/job-search/drafts/<id>.md and roles/<id>.md.
    """
    return await _run_guarded(
        "draft_application",
        lambda: _draft_result(role_id_or_text, company, title, score),
    )


def _draft_result(
    role_id_or_text: str, company: str = "", title: str = "", score: int = 0
) -> str:
    raw_input = role_id_or_text.strip()
    url = raw_input if raw_input.startswith(("http://", "https://")) else ""

    ad = _resolve_ad_text(role_id_or_text)
    if ad.startswith("could not fetch") or ad.startswith("LinkedIn links cannot"):
        return ad

    result = _draft_application(ad)
    if result.get("rejected"):
        return f"draft rejected: {result.get('reason', '')}"

    resolved_company, resolved_title = _resolve_company_title(ad, url, company, title)
    role_id = derive_role_id(ad, url, resolved_company, resolved_title)
    company = resolved_company or "unknown"
    title = resolved_title or "unknown"

    variant = result.get("cv_variant", "general")
    drafted = datetime.now(UTC).strftime("%Y-%m-%d")

    draft_content = (
        f"---\n"
        f"role_id: {role_id}\n"
        f"company: {_q(company)}\n"
        f"title: {_q(title)}\n"
        f"cv_variant: {variant}\n"
        f"drafted: {drafted}\n"
        f"---\n\n"
        f"# Draft for {title} at {company}\n\n"
        f"## CV to attach\n\n"
        f"{result.get('cv_file', '')}\n\n"
        f"{result.get('draft', '')}\n"
    )

    source, source_id = _classify_url(url)
    if not url:
        source = "manual"
    role_content = (
        f"---\n"
        f"company: {_q(company)}\n"
        f"title: {_q(title)}\n"
        f"source: {_q(source)}\n"
        f"source_id: {_q(source_id)}\n"
        f"url: {_q(url)}\n"
        f"score: {score}\n"
        f"cv_variant: {variant}\n"
        f"status: drafted\n"
        f"applied: null\n"
        f"next_action: review\n"
        f"next_action_date: null\n"
        f"---\n\n"
        f"# {title} at {company}\n\n"
        f"## Role description\n\n"
        f"{ad[:_ROLE_DESC_CAP]}\n"
    )

    write_draft_and_role(role_id, draft_content, role_content)

    return (
        f"draft written to job-search/drafts/{role_id}.md "
        f"and role job-search/roles/{role_id}.md"
    )


@mcp.tool(annotations=WRITE_TOOL)
async def set_status(role_id: str, status: str, note: str = "") -> str:
    """Set a role's status (applied, interviewing, offer, rejected, withdrawn)."""
    valid = {"applied", "interviewing", "offer", "rejected", "withdrawn"}
    if status not in valid:
        return f"invalid status: {status} (must be one of {', '.join(sorted(valid))})"

    roles = read_roles()
    role = next((r for r in roles if r.get("_id") == role_id), None)
    if not role:
        return f"role {role_id} not found"

    today = datetime.now(UTC).strftime("%Y-%m-%d")
    content = f"""---
company: {role.get('company', '')}
title: {role.get('title', '')}
source: {role.get('source', '')}
source_id: {role.get('source_id', '')}
url: {role.get('url', '')}
score: {role.get('score', 0)}
cv_variant: {role.get('cv_variant', 'general')}
status: {status}
applied: {today if status == 'applied' else role.get('applied', 'null')}
next_action: {note or status}
next_action_date: {today}
---

# {role.get('title', '')} at {role.get('company', '')}
"""
    update_role_status(role_id, content, status)
    return f"status set to {status} for {role_id}"


@mcp.custom_route("/healthz", methods=["GET"])
async def healthz(request: Request) -> JSONResponse:  # noqa: ARG001
    return JSONResponse({"status": "ok"})


def _authorized(request: Request) -> bool:
    auth = request.headers.get("authorization", "")
    expected = f"Bearer {TOKEN}"
    return secrets.compare_digest(auth, expected)


class BearerAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Any) -> Any:
        if request.url.path == "/healthz":
            return await call_next(request)
        if not _authorized(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return await call_next(request)


app = mcp.streamable_http_app()
app.add_middleware(BearerAuthMiddleware)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")