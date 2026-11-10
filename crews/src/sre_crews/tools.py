"""Tools available to the crews.

Two upstream MCP servers run as loopback sidecars and are exposed read-only via
CrewAI's ``MCPServerHTTP`` config with a static tool filter (ADR-0028). One local
tool, ``find_runbook``, searches the git-sync checkout of the handbook.
"""

from __future__ import annotations

import glob
import os
from pathlib import Path

from crewai.mcp.config import MCPServerHTTP
from crewai.mcp.filters import create_static_tool_filter
from crewai.tools import tool

HANDBOOK_ROOT = os.environ.get("HANDBOOK_ROOT", "/handbook/current")

K8S_TOOLS = [
    "pods_list",
    "pods_get",
    "pods_log",
    "events_list",
    "resources_list",
    "resources_get",
    "nodes_top",
    "pods_top",
]

GRAFANA_TOOLS = [
    "query_prometheus",
    "query_loki_logs",
    "list_datasources",
    "alerting_rules_read",
]

k8s_mcp = MCPServerHTTP(
    url="http://127.0.0.1:8002/mcp",
    tool_filter=create_static_tool_filter(allowed_tool_names=K8S_TOOLS),
)

grafana_mcp = MCPServerHTTP(
    url="http://127.0.0.1:8001/mcp",
    tool_filter=create_static_tool_filter(allowed_tool_names=GRAFANA_TOOLS),
)


def find_runbook(topic: str) -> str:
    """Search the handbook's runbooks for a topic.

    Looks for `docs/domains/**/runbook-*.md` under the handbook checkout and
    returns at most two matches, each truncated to 4,000 characters.
    """
    pattern = str(Path(HANDBOOK_ROOT) / "docs" / "domains" / "**" / "runbook-*.md")
    matches = sorted(glob.glob(pattern, recursive=True))
    query = topic.lower()
    hits = []
    for path in matches:
        try:
            text = Path(path).read_text(errors="replace")
        except OSError:
            continue
        if query in text.lower():
            hits.append((path, text[:4000]))
            if len(hits) == 2:
                break

    if not hits:
        return f"No runbook matched '{topic}'."

    out = []
    for path, text in hits:
        rel = path.removeprefix(str(Path(HANDBOOK_ROOT)) + "/")
        out.append(f"# {rel}\n\n{text}")
    return "\n\n---\n\n".join(out)


find_runbook_tool = tool(find_runbook)
