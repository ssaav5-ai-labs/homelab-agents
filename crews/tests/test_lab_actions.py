import asyncio

from sre_crews import lab_actions


def test_validate_restart_refuses_unknown_namespace():
    assert lab_actions.validate_restart(
        "hermes", "litellm", {"llm-gateway", "monitoring"}, set()
    ) == "namespace 'hermes' is not allowed"


def test_validate_restart_refuses_denied_workload():
    assert lab_actions.validate_restart(
        "llm-gateway", "postgres", {"llm-gateway"}, {("llm-gateway", "postgres")}
    ) == "deployment 'llm-gateway/postgres' is denied"


def test_validate_restart_allows_allowed_workload():
    assert (
        lab_actions.validate_restart(
            "monitoring", "alloy-operator", {"llm-gateway", "monitoring"}, set()
        )
        is None
    )


def test_denied_workloads_parses_env(monkeypatch):
    monkeypatch.setenv("DENIED_WORKLOADS", "llm-gateway/postgres, llm-gateway/litellm")
    assert lab_actions.denied_workloads() == {
        ("llm-gateway", "postgres"),
        ("llm-gateway", "litellm"),
    }


def test_restart_workload_refuses_before_api_call(monkeypatch):
    async def would_call_api(namespace, deployment):
        raise AssertionError("restart_workload reached the API for a refused request")

    monkeypatch.setattr(lab_actions, "_do_restart", would_call_api)
    monkeypatch.setenv("ALLOWED_NAMESPACES", "llm-gateway,monitoring")

    async def scenario() -> str:
        return await lab_actions.restart_workload("hermes", "litellm", "test")

    assert asyncio.run(scenario()) == "namespace 'hermes' is not allowed"


def test_restart_workload_refuses_denied_workload_before_api_call(monkeypatch):
    async def would_call_api(namespace, deployment):
        raise AssertionError("restart_workload reached the API for a denied workload")

    monkeypatch.setattr(lab_actions, "_do_restart", would_call_api)
    monkeypatch.setenv("ALLOWED_NAMESPACES", "llm-gateway,monitoring")
    monkeypatch.setenv("DENIED_WORKLOADS", "llm-gateway/postgres")

    async def scenario() -> str:
        return await lab_actions.restart_workload("llm-gateway", "postgres", "test")

    assert asyncio.run(scenario()) == "deployment 'llm-gateway/postgres' is denied"


def test_tool_and_annotations():
    listed = asyncio.run(lab_actions.mcp.list_tools())
    by_name = {t.name: t for t in listed}
    assert set(by_name) == {"restart_workload"}
    assert by_name["restart_workload"].annotations.destructiveHint is True
    assert by_name["restart_workload"].annotations.readOnlyHint is not True
