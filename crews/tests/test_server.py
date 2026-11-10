import asyncio
import threading

from sre_crews import server


class FakeRequest:
    def __init__(self, auth=None):
        self.headers = {"authorization": auth} if auth else {}


def test_authorized_correct_token():
    server.TOKEN = "tok"
    assert server._authorized(FakeRequest("Bearer tok")) is True


def test_authorized_wrong_and_missing_token():
    server.TOKEN = "tok"
    assert server._authorized(FakeRequest("Bearer nope")) is False
    assert server._authorized(FakeRequest()) is False


def test_busy_rule(monkeypatch):
    lock = threading.Lock()
    lock.acquire()
    monkeypatch.setattr(server, "_busy", lock)
    assert server._run_guarded("x", lambda: "ok") == "busy, try again in a few minutes"


def test_run_guarded_returns_result(monkeypatch):
    monkeypatch.setattr(server, "_busy", threading.Lock())
    assert server._run_guarded("x", lambda: "ok") == "ok"


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

    monkeypatch.setattr(investigate, "make_llm", stub_llm)
    monkeypatch.setattr("crewai.Crew.kickoff", lambda self: "report")
    assert investigate.investigate_alert({"alertname": "X"}) == "report"
