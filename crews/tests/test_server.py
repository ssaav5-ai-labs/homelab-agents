import asyncio

from sre_crews import server


class FakeRequest:
    def __init__(self, auth=None):
        self.headers = {"authorization": auth} if auth else {}


async def _ok() -> str:
    return "ok"


def test_authorized_correct_token():
    server.TOKEN = "tok"
    assert server._authorized(FakeRequest("Bearer tok")) is True


def test_authorized_wrong_and_missing_token():
    server.TOKEN = "tok"
    assert server._authorized(FakeRequest("Bearer nope")) is False
    assert server._authorized(FakeRequest()) is False


def test_busy_rule(monkeypatch):
    async def scenario() -> None:
        lock = asyncio.Lock()
        await lock.acquire()
        monkeypatch.setattr(server, "_busy", lock)
        assert await server._run_guarded("x", _ok) == "busy, try again in a few minutes"

    asyncio.run(scenario())


def test_run_guarded_returns_result(monkeypatch):
    async def scenario() -> None:
        monkeypatch.setattr(server, "_busy", asyncio.Lock())
        assert await server._run_guarded("x", _ok) == "ok"

    asyncio.run(scenario())


def test_tools_and_read_only_annotations():
    listed = asyncio.run(server.mcp.list_tools())
    by_name = {t.name: t for t in listed}
    assert set(by_name) == {"investigate_alert", "weekly_capacity_report", "find_runbook"}
    for tool in by_name.values():
        assert tool.annotations.readOnlyHint is True


def test_investigate_builds_with_stub_llm(monkeypatch):
    from crewai import LLM

    from sre_crews import investigate

    def stub_llm(alias: str) -> LLM:
        return LLM(model=f"openai/{alias}", base_url="http://127.0.0.1:9/v1", api_key="k")

    async def stub_kickoff_async(self, inputs=None):
        return "report"

    monkeypatch.setattr(investigate, "make_llm", stub_llm)
    monkeypatch.setattr("crewai.Crew.kickoff_async", stub_kickoff_async)
    assert asyncio.run(investigate.investigate_alert({"alertname": "X"})) == "report"


def _stub_sync_kickoff_that_rejects_a_running_loop():
    def stub_kickoff(self, inputs=None):
        if asyncio.get_running_loop() is not None:
            raise RuntimeError(
                "Agent execution was invoked synchronously from within a running event loop"
            )
        return "sync-report"

    return stub_kickoff


def test_investigate_alert_handler_kickoff_async(monkeypatch):
    from crewai import LLM, Crew

    from sre_crews import investigate

    def stub_llm(alias: str) -> LLM:
        return LLM(model=f"openai/{alias}", base_url="http://127.0.0.1:9/v1", api_key="k")

    async def stub_kickoff_async(self, inputs=None):
        return "async-report"

    monkeypatch.setattr(investigate, "make_llm", stub_llm)
    monkeypatch.setattr(Crew, "kickoff", _stub_sync_kickoff_that_rejects_a_running_loop())
    monkeypatch.setattr(Crew, "kickoff_async", stub_kickoff_async)

    async def scenario() -> str:
        monkeypatch.setattr(server, "_busy", asyncio.Lock())
        return await server.investigate_alert({"alertname": "X"})

    assert asyncio.run(scenario()) == "async-report"


def test_weekly_capacity_report_handler_async(monkeypatch):
    from sre_crews import capacity

    async def stub_pods():
        return [
            capacity.ContainerData(
                "sre", "p-abc", "app", "app", "node1", 512 * capacity.MIB, 1024 * capacity.MIB
            )
        ]

    async def stub_peaks():
        return {("sre", "app", "app"): 100 * capacity.MIB}

    async def stub_verdict(report):
        return "room for about 384 Mi more"

    monkeypatch.setattr(capacity, "_fetch_pods", stub_pods)
    monkeypatch.setattr(capacity, "_fetch_peaks", stub_peaks)
    monkeypatch.setattr(capacity, "_verdict", stub_verdict)

    async def scenario() -> str:
        monkeypatch.setattr(server, "_busy", asyncio.Lock())
        return await server.weekly_capacity_report()

    result = asyncio.run(scenario())
    assert "app" in result
    assert "room for about 384 Mi more" in result
