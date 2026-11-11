"""Minimal loopback MCP client for deterministic data fetches.

The crews normally reach the k8s-mcp and grafana-mcp sidecars through CrewAI's
``MCPServerHTTP`` config, which wraps each tool in a sync ``_run`` that does not
behave under an async crew runner and, on failure, surfaces only a generic
"Invalid request" on the server side. For the capacity report the data must be
real and reproducible, so it calls the two sidecars directly through the ``mcp``
SDK's streamable-http client instead.

Every call is logged with the tool name, the argument keys (never values), and
the outcome; an error is logged with its first 200 characters so a future
failure names itself.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from mcp.types import CallToolResult

logger = logging.getLogger("sre-crews.mcp")

MAX_ERROR_CHARS = 200


@dataclass
class McpResult:
    """One tool call result: the text content and any structured content."""

    text: str
    structured: Any


def _text_of(result: CallToolResult) -> str:
    parts: list[str] = []
    for block in result.content:
        if getattr(block, "type", None) == "text":
            parts.append(block.text)
    return "\n".join(parts)


async def call_tool(url: str, name: str, arguments: dict[str, Any] | None = None) -> McpResult:
    """Call a tool on a loopback MCP server and return its result.

    Raises ``RuntimeError`` with the first ``MAX_ERROR_CHARS`` of the server's
    error message when ``isError`` is set.
    """
    arguments = arguments or {}
    async with streamablehttp_client(url) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(name, arguments)

    if result.isError:
        error_text = _text_of(result)
        logger.error(
            "mcp_call url=%s tool=%s args=%s isError=true error=%s",
            url,
            name,
            sorted(arguments.keys()),
            error_text[:MAX_ERROR_CHARS],
        )
        raise RuntimeError(f"{name}: {error_text[:MAX_ERROR_CHARS]}")

    text = _text_of(result)
    logger.info(
        "mcp_call url=%s tool=%s args=%s isError=false chars=%d",
        url,
        name,
        sorted(arguments.keys()),
        len(text),
    )
    return McpResult(text=text, structured=result.structuredContent)
