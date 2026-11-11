"""The ``weekly_capacity_report`` tool: fetch and compute in code, then a verdict.

The data (memory requests/limits from Kubernetes, 7-day peaks from Grafana) is
fetched deterministically in code through the loopback MCP sidecars and turned
into the table and per-node totals with plain Python. The LLM's only job is to
write the one-line verdict from the computed table, so a bad query can no longer
produce invented workloads, nodes or ``kubectl`` commands.

If a fetch fails or returns no rows, the tool returns
``capacity report unavailable: <which>`` and no table.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from typing import Any

from .llm import make_llm
from .mcp_client import McpResult, call_tool

K8S_MCP_URL = "http://127.0.0.1:8002/mcp"
GRAFANA_MCP_URL = "http://127.0.0.1:8001/mcp"

# Grafana Cloud Prometheus datasource UID (playbook 05 step 5 run note).
PROMETHEUS_DATASOURCE_UID = "grafanacloud-prom"

PEAK_QUERY = (
    'max_over_time(container_memory_working_set_bytes{cluster="homelab", container!=""}[7d])'
)

MIB = 1024 * 1024
ROUND_MIB = 16 * MIB
TOP_N = 10
PEAK_MULTIPLIER = 1.25
PEAK_HEADROOM = 128 * MIB


class CapacityUnavailable(Exception):
    """A fetch failed or returned no rows; the report is withheld."""


@dataclass
class ContainerData:
    namespace: str
    pod: str
    workload: str
    container: str
    node: str
    request_bytes: int
    limit_bytes: int


@dataclass
class WorkloadRow:
    namespace: str
    workload: str
    container: str
    node: str
    request_bytes: int
    limit_bytes: int
    peak_bytes: int
    proposed_request: int
    proposed_limit: int

    @property
    def gap_bytes(self) -> int:
        return self.request_bytes - self.proposed_request


@dataclass
class Report:
    rows: list[WorkloadRow] = field(default_factory=list)
    node_before: dict[str, int] = field(default_factory=dict)
    node_after: dict[str, int] = field(default_factory=dict)

    @property
    def total_reclaimable(self) -> int:
        return sum(max(0, r.gap_bytes) for r in self.rows)


def parse_memory_quantity(value: str) -> int:
    """Parse a Kubernetes memory quantity to an integer number of bytes."""
    value = (value or "").strip()
    if value == "":
        return 0
    match = re.fullmatch(r"(\d+(?:\.\d+)?)([A-Za-z]*)", value)
    if not match:
        raise ValueError(f"unparseable memory quantity: {value!r}")
    number = float(match.group(1))
    suffix = match.group(2)
    binary = {"Ki": 1024, "Mi": 1024**2, "Gi": 1024**3, "Ti": 1024**4, "Pi": 1024**5, "Ei": 1024**6}
    decimal = {"k": 1e3, "M": 1e6, "G": 1e9, "T": 1e12, "P": 1e15, "E": 1e18}
    if suffix == "":
        return int(number)
    if suffix == "m":
        return int(number / 1000)
    if suffix in binary:
        return int(number * binary[suffix])
    if suffix in decimal:
        return int(number * decimal[suffix])
    raise ValueError(f"unparseable memory quantity suffix: {value!r}")


def round_up_to(value: int, unit: int) -> int:
    return int(math.ceil(value / unit) * unit)


def propose_request(peak_bytes: int) -> int:
    return round_up_to(int(peak_bytes * PEAK_MULTIPLIER), ROUND_MIB)


def propose_limit(peak_bytes: int, request_bytes: int) -> int:
    return round_up_to(max(request_bytes * 2, peak_bytes + PEAK_HEADROOM), ROUND_MIB)


def _owner_of(pod: dict[str, Any], rs_owner: dict[str, str]) -> str:
    """Resolve a pod's top-level workload name (ReplicaSet -> Deployment)."""
    refs = (pod.get("metadata") or {}).get("ownerReferences") or []
    if not refs:
        return (pod.get("metadata") or {}).get("name", "?")
    ref = refs[0]
    kind = ref.get("kind", "")
    name = ref.get("name", "?")
    if kind == "ReplicaSet":
        return rs_owner.get(name, name)
    return name


def _as_items(structured: Any) -> list[Any]:
    if isinstance(structured, list):
        return structured
    if isinstance(structured, dict):
        items = structured.get("items")
        if isinstance(items, list):
            return items
    return []


def parse_pods(structured: Any, rs_owner: dict[str, str]) -> list[ContainerData]:
    """Extract per-container request/limit data from a ``resources_list`` result."""
    out: list[ContainerData] = []
    for pod in _as_items(structured):
        if not isinstance(pod, dict):
            continue
        metadata = pod.get("metadata") or {}
        spec = pod.get("spec") or {}
        namespace = metadata.get("namespace", "")
        pod_name = metadata.get("name", "")
        node = spec.get("nodeName", "")
        workload = _owner_of(pod, rs_owner)
        for container in spec.get("containers") or []:
            if not isinstance(container, dict):
                continue
            resources = container.get("resources") or {}
            requests = resources.get("requests") or {}
            limits = resources.get("limits") or {}
            out.append(
                ContainerData(
                    namespace=namespace,
                    pod=pod_name,
                    workload=workload,
                    container=container.get("name", ""),
                    node=node,
                    request_bytes=parse_memory_quantity(requests.get("memory", "")),
                    limit_bytes=parse_memory_quantity(limits.get("memory", "")),
                )
            )
    return out


def parse_replicasets(structured: Any) -> dict[str, str]:
    """Map a ReplicaSet name to its owning Deployment name."""
    out: dict[str, str] = {}
    for rs in _as_items(structured):
        if not isinstance(rs, dict):
            continue
        metadata = rs.get("metadata") or {}
        name = metadata.get("name", "")
        refs = metadata.get("ownerReferences") or []
        if refs and refs[0].get("kind") == "Deployment":
            out[name] = refs[0].get("name", name)
    return out


def _prometheus_data(result: McpResult) -> dict[str, Any]:
    structured = result.structured
    if isinstance(structured, dict):
        data = structured.get("data")
        if isinstance(data, dict):
            return data
        if isinstance(data, str):
            try:
                parsed = json.loads(data)
            except json.JSONDecodeError:
                return {}
            return parsed if isinstance(parsed, dict) else {}
    text = result.text.strip()
    if text:
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return {}
        if isinstance(parsed, dict) and isinstance(parsed.get("data"), dict):
            return parsed["data"]
    return {}


def parse_peaks(result: McpResult) -> dict[tuple[str, str, str], int]:
    """Extract peak bytes keyed by ``(namespace, pod, container)``."""
    data = _prometheus_data(result)
    peaks: dict[tuple[str, str, str], int] = {}
    for series in data.get("result") or []:
        metric = series.get("metric") or {}
        key = (
            str(metric.get("namespace", "")),
            str(metric.get("pod", "")),
            str(metric.get("container", "")),
        )
        value = series.get("value")
        if isinstance(value, list | tuple) and len(value) >= 2:
            peaks[key] = int(float(value[1]))
    return peaks


def compute_report(
    containers: list[ContainerData], peaks: dict[tuple[str, str, str], int]
) -> Report:
    """Join containers to peaks, aggregate by workload, compute proposals."""
    by_workload: dict[tuple[str, str, str], list[ContainerData]] = {}
    for item in containers:
        by_workload.setdefault((item.namespace, item.workload, item.container), []).append(item)

    rows: list[WorkloadRow] = []
    for (namespace, workload, container), items in by_workload.items():
        peak_bytes = max((peaks.get((namespace, i.pod, container), 0) for i in items), default=0)
        if peak_bytes <= 0:
            continue
        request_bytes = max((i.request_bytes for i in items), default=0)
        limit_bytes = max((i.limit_bytes for i in items), default=0)
        node = items[0].node
        proposed_request = propose_request(peak_bytes)
        proposed_limit = propose_limit(peak_bytes, proposed_request)
        rows.append(
            WorkloadRow(
                namespace=namespace,
                workload=workload,
                container=container,
                node=node,
                request_bytes=request_bytes,
                limit_bytes=limit_bytes,
                peak_bytes=peak_bytes,
                proposed_request=proposed_request,
                proposed_limit=proposed_limit,
            )
        )

    rows.sort(key=lambda r: r.gap_bytes, reverse=True)
    top = rows[:TOP_N]

    node_before: dict[str, int] = {}
    node_after: dict[str, int] = {}
    for row in top:
        node_before[row.node] = node_before.get(row.node, 0) + row.request_bytes
        node_after[row.node] = node_after.get(row.node, 0) + row.proposed_request

    return Report(rows=top, node_before=node_before, node_after=node_after)


def validate_workloads(report: Report, containers: list[ContainerData]) -> None:
    """Raise if a report row names a workload not present in the fetched data."""
    fetched = {(c.namespace, c.workload) for c in containers}
    unknown = sorted(
        {(r.namespace, r.workload) for r in report.rows} - fetched
    )
    if unknown:
        raise ValueError(f"workload(s) not in fetched Kubernetes data: {unknown}")


def format_bytes(value: int) -> str:
    return f"{value // MIB}Mi"


def format_report(report: Report) -> str:
    header = (
        "| namespace | workload | container | node | request | limit | peak | "
        "proposed request | proposed limit |\n"
        "|---|---|---|---|---|---|---|---|---|"
    )
    lines = [header]
    for r in report.rows:
        cells = [
            r.namespace,
            r.workload,
            r.container,
            r.node,
            format_bytes(r.request_bytes),
            format_bytes(r.limit_bytes),
            format_bytes(r.peak_bytes),
            format_bytes(r.proposed_request),
            format_bytes(r.proposed_limit),
        ]
        lines.append("| " + " | ".join(cells) + " |")
    lines.append("")
    lines.append("Per-node requests before/after (Mi):")
    for node in sorted(set(report.node_before) | set(report.node_after)):
        before = report.node_before.get(node, 0) // MIB
        after = report.node_after.get(node, 0) // MIB
        lines.append(f"- {node}: {before} -> {after}")
    return "\n".join(lines)


async def _fetch_pods() -> list[ContainerData]:
    try:
        rs_result = await call_tool(
            K8S_MCP_URL, "resources_list", {"apiVersion": "apps/v1", "kind": "ReplicaSet"}
        )
        rs_owner = parse_replicasets(rs_result.structured)
        pods_result = await call_tool(
            K8S_MCP_URL, "resources_list", {"apiVersion": "v1", "kind": "Pod"}
        )
        containers = parse_pods(pods_result.structured, rs_owner)
    except CapacityUnavailable:
        raise
    except Exception as exc:  # noqa: BLE001
        raise CapacityUnavailable(f"k8s ({exc})") from exc
    if not containers:
        raise CapacityUnavailable("k8s (no pods)")
    return containers


async def _fetch_peaks() -> dict[tuple[str, str, str], int]:
    try:
        result = await call_tool(
            GRAFANA_MCP_URL,
            "query_prometheus",
            {
                "datasourceUid": PROMETHEUS_DATASOURCE_UID,
                "expr": PEAK_QUERY,
                "queryType": "instant",
                "endTime": "now",
            },
        )
    except Exception as exc:  # noqa: BLE001
        raise CapacityUnavailable(f"grafana ({exc})") from exc
    peaks = parse_peaks(result)
    if not peaks:
        raise CapacityUnavailable("grafana (no data)")
    return peaks


async def _verdict(report: Report) -> str:
    n = report.total_reclaimable // MIB
    table = format_report(report)
    prompt = (
        "Here is this week's computed capacity table:\n\n"
        f"{table}\n\n"
        f"The total memory that can be reclaimed is {n} Mi. "
        "Write a single one-line verdict of the exact form "
        f"'room for about {n} Mi more'. Output only that line."
    )
    try:
        llm = make_llm("code")
        verdict = (await llm.acall(prompt)).strip()
        if verdict:
            return verdict
    except Exception:  # noqa: BLE001
        pass
    return f"room for about {n} Mi more"


async def weekly_capacity_report() -> str:
    try:
        containers = await _fetch_pods()
        peaks = await _fetch_peaks()
    except CapacityUnavailable as exc:
        return f"capacity report unavailable: {exc}"
    report = compute_report(containers, peaks)
    if not report.rows:
        return "capacity report unavailable: no containers with both a request and a 7-day peak"
    validate_workloads(report, containers)
    verdict = await _verdict(report)
    return format_report(report) + "\n\n" + verdict
