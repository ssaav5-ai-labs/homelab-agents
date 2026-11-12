import asyncio
import json

import pytest

from sre_crews import capacity
from sre_crews.capacity import (
    MIB,
    ContainerData,
    Report,
    WorkloadRow,
    compute_report,
    group_peaks_by_workload,
    parse_memory_quantity,
    parse_peaks,
    parse_pods,
    validate_workloads,
)
from sre_crews.mcp_client import McpResult


def test_parse_memory_quantity():
    assert parse_memory_quantity("512Mi") == 512 * MIB
    assert parse_memory_quantity("1Gi") == 1024 * MIB
    assert parse_memory_quantity("") == 0
    assert parse_memory_quantity("1048576") == 1048576


def test_parse_pods_resolves_replicaset_owner():
    structured = {
        "items": [
            {
                "metadata": {
                    "name": "app-7b9c4d",
                    "namespace": "sre",
                    "ownerReferences": [{"kind": "ReplicaSet", "name": "app-7b9c4d"}],
                },
                "spec": {
                    "nodeName": "node1",
                    "containers": [
                        {
                            "name": "app",
                            "resources": {
                                "requests": {"memory": "512Mi"},
                                "limits": {"memory": "1Gi"},
                            },
                        }
                    ],
                },
            }
        ]
    }
    rs_owner = {"app-7b9c4d": "app"}
    containers = parse_pods(structured, rs_owner)
    assert len(containers) == 1
    assert containers[0].workload == "app"
    assert containers[0].request_bytes == 512 * MIB
    assert containers[0].limit_bytes == 1024 * MIB


def test_compute_report_fixture():
    containers = [
        ContainerData("sre", "crews-abc", "crews", "crews", "node1", 512 * MIB, 1024 * MIB),
        ContainerData("sre", "gateway-abc", "gateway", "app", "node2", 1024 * MIB, 2048 * MIB),
    ]
    peaks = {
        ("sre", "crews-abc", "crews"): 100 * MIB,
        ("sre", "gateway-abc", "app"): 400 * MIB,
    }
    report = compute_report(containers, peaks)

    assert [r.workload for r in report.rows] == ["gateway", "crews"]
    assert report.rows[0].gap_bytes == 512 * MIB
    assert report.rows[0].proposed_request == 512 * MIB
    assert report.rows[1].proposed_request == 128 * MIB
    assert report.rows[1].proposed_limit == 256 * MIB
    assert report.node_before == {"node1": 512 * MIB, "node2": 1024 * MIB}
    assert report.node_after == {"node1": 128 * MIB, "node2": 512 * MIB}
    assert report.total_reclaimable == 896 * MIB


def _pod() -> dict:
    return {
        "metadata": {
            "name": "app-7b9c4d",
            "namespace": "sre",
            "ownerReferences": [{"kind": "ReplicaSet", "name": "app-7b9c4d"}],
        },
        "spec": {
            "nodeName": "node1",
            "containers": [
                {
                    "name": "app",
                    "resources": {
                        "requests": {"memory": "512Mi"},
                        "limits": {"memory": "1Gi"},
                    },
                }
            ],
        },
    }


def _series() -> dict:
    return {
        "metric": {"namespace": "sre", "pod": "app-7b9c4d", "container": "app"},
        "value": [1730000000, "104857600"],
    }


def test_empty_pods_fetch_is_unavailable(monkeypatch):
    from sre_crews.mcp_client import McpResult

    async def fake_call(url, name, arguments):
        return McpResult(text="", structured={"items": []})

    monkeypatch.setattr(capacity, "call_tool", fake_call)
    result = asyncio.run(capacity.weekly_capacity_report())
    assert result == "capacity report unavailable: k8s (no pods)"


def test_empty_peak_fetch_is_unavailable(monkeypatch):
    from sre_crews.mcp_client import McpResult

    async def fake_call(url, name, arguments):
        if "8002" in url:
            return McpResult(text="", structured={"items": [_pod()]})
        return McpResult(text="", structured={"data": {"resultType": "vector", "result": []}})

    monkeypatch.setattr(capacity, "call_tool", fake_call)
    result = asyncio.run(capacity.weekly_capacity_report())
    assert result == "capacity report unavailable: grafana (no data)"


def test_validator_rejects_unknown_name():
    report = Report(rows=[WorkloadRow("sre", "does-not-exist", "app", "node1", 0, 0, 0, 0, 0)])
    containers = [ContainerData("sre", "real-abc", "real", "app", "node1", 512 * MIB, 1024 * MIB)]
    with pytest.raises(ValueError, match="not in fetched"):
        validate_workloads(report, containers)


def test_validator_accepts_known_name():
    report = Report(rows=[WorkloadRow("sre", "real", "app", "node1", 0, 0, 0, 0, 0)])
    containers = [ContainerData("sre", "real-abc", "real", "app", "node1", 512 * MIB, 1024 * MIB)]
    validate_workloads(report, containers)


def _prometheus_vector() -> dict:
    # Real mcp-grafana v2.2.0 query_prometheus response shape: "data" is a bare
    # array of series (no {"resultType": ..., "result": [...]} wrapper). Two
    # cAdvisor series for the same pod share (namespace, pod, container).
    return {
        "data": [
            {
                "metric": {
                    "cluster": "homelab",
                    "container": "litellm",
                    "namespace": "llm-gateway",
                    "pod": "litellm-9bd4dfc66-brxh2",
                    "node": "k3s-02",
                },
                "value": [1794402183.693, "1039847424"],
            },
            {
                "metric": {
                    "cluster": "homelab",
                    "container": "litellm",
                    "namespace": "llm-gateway",
                    "pod": "litellm-9bd4dfc66-brxh2",
                    "node": "k3s-02",
                },
                "value": [1794402183.693, "967475200"],
            },
        ],
        "exploreUrl": "https://example.grafana.net/explore?panes=...",
    }


def test_parse_peaks_grafana_v2_vector_shape():
    payload = _prometheus_vector()
    peaks = parse_peaks(
        McpResult(text=json.dumps(payload), structured=payload)
    )
    assert peaks == {
        ("llm-gateway", "litellm-9bd4dfc66-brxh2", "litellm"): 1039847424,
    }


def test_parse_peaks_grafana_v2_vector_shape_text_only():
    payload = _prometheus_vector()
    peaks = parse_peaks(McpResult(text=json.dumps(payload), structured=None))
    assert peaks == {
        ("llm-gateway", "litellm-9bd4dfc66-brxh2", "litellm"): 1039847424,
    }


def test_parse_peaks_range_values_shape():
    payload = {
        "data": [
            {
                "metric": {"namespace": "sre", "pod": "app-7b9c4d", "container": "app"},
                "values": [[1730000000, "104857600"], [1730000060, "157286400"]],
            }
        ]
    }
    peaks = parse_peaks(McpResult(text=json.dumps(payload), structured=payload))
    assert peaks == {("sre", "app-7b9c4d", "app"): 157286400}


def test_group_peaks_by_workload_folds_rollout_pods():
    # A Deployment rolled over mid-week: two cAdvisor series, one per pod
    # name, share the same workload. The old pod is no longer in `containers`,
    # so it is matched by longest known-workload prefix; the higher peak wins.
    containers = [
        ContainerData(
            "llm-gateway",
            "litellm-9bd4dfc66-brxh2",
            "litellm",
            "litellm",
            "k3s-02",
            512 * MIB,
            1024 * MIB,
        ),
    ]
    peaks = {
        ("llm-gateway", "litellm-9bd4dfc66-brxh2", "litellm"): 967475200,
        ("llm-gateway", "litellm-6a1b2c3d4-zxk9p", "litellm"): 1039847424,
    }
    grouped = group_peaks_by_workload(peaks, containers)
    assert grouped == {("llm-gateway", "litellm", "litellm"): 1039847424}


def test_group_peaks_by_workload_keeps_hyphenated_name():
    containers = [
        ContainerData(
            "monitoring", "node-exporter-abc12", "node-exporter", "node-exporter", "k3s-01", 0, 0
        ),
    ]
    peaks = {("monitoring", "node-exporter-abc12", "node-exporter"): 123456}
    assert group_peaks_by_workload(peaks, containers) == {
        ("monitoring", "node-exporter", "node-exporter"): 123456
    }


def test_compute_report_drops_underprovisioned_workloads():
    # A workload whose 7-day peak is above its request needs a raise, not a
    # reclaim: it must not appear in the report or its per-node totals.
    containers = [
        ContainerData("sre", "crews-abc", "crews", "crews", "node1", 512 * MIB, 1024 * MIB),
        ContainerData("sre", "busy-abc", "busy", "app", "node1", 256 * MIB, 1024 * MIB),
    ]
    peaks = {
        ("sre", "crews-abc", "crews"): 100 * MIB,  # over-provisioned -> reclaimable
        ("sre", "busy-abc", "app"): 512 * MIB,  # under-provisioned -> needs a raise
    }
    report = compute_report(containers, peaks)
    assert [r.workload for r in report.rows] == ["crews"]
    assert report.node_before == {"node1": 512 * MIB}
    assert report.node_after == {"node1": 128 * MIB}


def test_total_reclaimable_matches_node_deltas():
    # The verdict number is total_reclaimable; it must equal the byte-level
    # sum of per-node before/after deltas so the table and the verdict agree.
    containers = [
        ContainerData("sre", "crews-abc", "crews", "crews", "node1", 512 * MIB, 1024 * MIB),
        ContainerData("sre", "gateway-abc", "gateway", "app", "node2", 1024 * MIB, 2048 * MIB),
    ]
    peaks = {
        ("sre", "crews-abc", "crews"): 100 * MIB,
        ("sre", "gateway-abc", "app"): 400 * MIB,
    }
    report = compute_report(containers, peaks)
    deltas = sum(report.node_before.values()) - sum(report.node_after.values())
    assert report.total_reclaimable == deltas
