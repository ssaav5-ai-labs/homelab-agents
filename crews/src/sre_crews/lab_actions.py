"""The lab-actions MCP server: one write action behind an approval gate.

Separate from the read-only crews server. ``restart_workload`` deletes a
Deployment's pods one at a time so the Deployment recreates them (a
``kubectl rollout restart`` would edit the pod template, which Argo CD's
self-heal reverts). It is destructive, so Hermes marks the server untrusted
and every call waits for an explicit approval; alert-driven (unattended)
sessions deny it (ADR-0029).

Refusals happen before any API call: a namespace outside ``ALLOWED_NAMESPACES``
or a deployment named in ``DENIED_WORKLOADS`` is turned down server-side.
"""

from __future__ import annotations

import asyncio
import logging
import os
import secrets
import time
from typing import Any

from kubernetes import client as k8s
from kubernetes import config as k8s_config
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger("lab-actions")

TOKEN = os.environ["LAB_ACTIONS_TOKEN"]

DESTRUCTIVE = ToolAnnotations(destructiveHint=True)

REPLACEMENT_TIMEOUT = 120  # seconds

mcp = FastMCP(
    "lab-actions",
    host="0.0.0.0",
    port=8000,
    streamable_http_path="/mcp",
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[
            "lab-actions.sre.svc:8000",
            "lab-actions.sre.svc.cluster.local:8000",
        ],
    ),
)


def allowed_namespaces() -> set[str]:
    raw = os.environ.get("ALLOWED_NAMESPACES", "")
    return {n.strip() for n in raw.split(",") if n.strip()}


def denied_workloads() -> set[tuple[str, str]]:
    raw = os.environ.get("DENIED_WORKLOADS", "")
    out: set[tuple[str, str]] = set()
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        namespace, sep, name = entry.partition("/")
        if sep and namespace and name:
            out.add((namespace, name))
    return out


def validate_restart(
    namespace: str,
    deployment: str,
    allowed: set[str],
    denied: set[tuple[str, str]],
) -> str | None:
    """Return the reason the restart is refused, or ``None`` if it may proceed."""
    if namespace not in allowed:
        return f"namespace '{namespace}' is not allowed"
    if (namespace, deployment) in denied:
        return f"deployment '{namespace}/{deployment}' is denied"
    return None


def _pod_is_ready(pod: Any) -> bool:
    status = pod.status
    if status is None or status.phase != "Running":
        return False
    for condition in status.conditions or []:
        if condition.type == "Ready" and condition.status == "True":
            return True
    return False


async def _wait_for_replacement(
    core: Any,
    namespace: str,
    label_selector: str,
    deleted_name: str,
    timeout: int = REPLACEMENT_TIMEOUT,
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        pods = core.list_namespaced_pod(
            namespace=namespace, label_selector=label_selector
        ).items
        for pod in pods:
            if pod.metadata.name != deleted_name and _pod_is_ready(pod):
                return
        await asyncio.sleep(2)
    raise TimeoutError(f"no Ready replacement pod for {deleted_name} within {timeout}s")


async def _do_restart(namespace: str, deployment: str) -> str:
    k8s_config.load_incluster_config()
    apps = k8s.AppsV1Api()
    core = k8s.CoreV1Api()

    dep = apps.read_namespaced_deployment(name=deployment, namespace=namespace)
    selector = (dep.spec.selector.match_labels) or {}
    label_selector = ",".join(f"{k}={v}" for k, v in sorted(selector.items()))
    pods = core.list_namespaced_pod(
        namespace=namespace, label_selector=label_selector
    ).items

    restarted = 0
    for pod in pods:
        core.delete_namespaced_pod(name=pod.metadata.name, namespace=namespace)
        await _wait_for_replacement(core, namespace, label_selector, pod.metadata.name)
        restarted += 1
    return f"restarted {restarted} pod(s) of {namespace}/{deployment}"


@mcp.tool(annotations=DESTRUCTIVE)
async def restart_workload(namespace: str, deployment: str, reason: str) -> str:
    """Restart a Deployment by deleting its pods one at a time.

    The Deployment recreates each pod. Only namespaces in ALLOWED_NAMESPACES are
    accepted, and DENIED_WORKLOADS is refused outright. Every call is logged.
    """
    logger.info(
        "restart requested namespace=%s deployment=%s reason=%s",
        namespace,
        deployment,
        reason,
    )
    refused = validate_restart(
        namespace, deployment, allowed_namespaces(), denied_workloads()
    )
    if refused:
        logger.info("restart refused namespace=%s deployment=%s", namespace, deployment)
        return refused
    try:
        result = await _do_restart(namespace, deployment)
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "restart error namespace=%s deployment=%s error=%s",
            namespace,
            deployment,
            exc,
        )
        return f"error: {exc}"
    logger.info("restart done namespace=%s deployment=%s", namespace, deployment)
    return result


def _authorized(request: Request) -> bool:
    auth = request.headers.get("authorization", "")
    return secrets.compare_digest(auth, f"Bearer {TOKEN}")


class BearerAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Any) -> Any:
        if request.url.path == "/healthz":
            return await call_next(request)
        if not _authorized(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return await call_next(request)


@mcp.custom_route("/healthz", methods=["GET"])
async def healthz(request: Request) -> JSONResponse:  # noqa: ARG001
    return JSONResponse({"status": "ok"})


app = mcp.streamable_http_app()
app.add_middleware(BearerAuthMiddleware)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
