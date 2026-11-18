"""The job-search MCP server: read-only scoring, drafting with approval hints.

Streamable HTTP on 0.0.0.0:8000/mcp, bearer ``JOBS_MCP_TOKEN``, one draft at
a time. Tools with ``readOnlyHint: false`` (draft, set_status) prompt Hermes
for ``Allow once``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
import time
from datetime import UTC, datetime
from typing import Any

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
    write_draft,
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
    today = datetime.now(UTC).strftime("%Y-%m-%d")

    for role in roles:
        status = role.get("status", "unknown")
        by_status.setdefault(status, []).append(role)
        next_date = role.get("next_action_date", "")
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
async def draft_application(role_id_or_text: str) -> str:
    """Draft a CV summary and cover note for a role. Accepts ad text or a role ID.

    Writes to career-vault/job-search/drafts/<id>.md.
    """
    return await _run_guarded(
        "draft_application",
        lambda: _draft_result(role_id_or_text),
    )


def _draft_result(role_id_or_text: str) -> str:
    import hashlib

    ad = _resolve_ad_text(role_id_or_text)
    if ad.startswith("could not fetch") or ad.startswith("LinkedIn links cannot"):
        return ad

    result = _draft_application(ad)
    if result.get("rejected"):
        return f"draft rejected: {result.get('reason', '')}"

    role_id = role_id_or_text.strip()
    if not role_id.startswith(("http://", "https://")):
        pass
    else:
        role_id = hashlib.blake2b(ad[:200].encode(), digest_size=8).hexdigest()

    draft_content = f"""---
role_id: {role_id}
cv_variant: {result.get('cv_variant', 'general')}
drafted: {datetime.now(UTC).strftime('%Y-%m-%d')}
---

# Draft for role {role_id}

## CV to attach

{result.get('cv_file', '')}

{result.get('draft', '')}
"""
    write_draft(role_id, draft_content)

    return f"draft written to job-search/drafts/{role_id}.md"


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