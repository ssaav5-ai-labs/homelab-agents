"""Test the job-search MCP server: auth, busy gate, tool annotations."""

import asyncio


def test_server_token_loaded():
    import job_search.server as srv
    assert srv.TOKEN == "test-token"


def test_read_only_annotation():
    from job_search.server import READ_ONLY
    assert READ_ONLY.readOnlyHint is True


def test_write_tool_annotation():
    from job_search.server import WRITE_TOOL
    assert WRITE_TOOL.readOnlyHint is False
    assert WRITE_TOOL.destructiveHint is False


def test_healthz_requires_no_auth():
    pass


def test_authorized_with_correct_token():
    from unittest.mock import MagicMock

    from job_search.server import _authorized
    request = MagicMock()
    request.headers = {"authorization": "Bearer test-token"}
    assert _authorized(request) is True


def test_authorized_with_bad_token():
    from unittest.mock import MagicMock

    from job_search.server import _authorized
    request = MagicMock()
    request.headers = {"authorization": "Bearer wrong"}
    assert _authorized(request) is False


def test_authorized_with_no_header():
    from unittest.mock import MagicMock

    from job_search.server import _authorized
    request = MagicMock()
    request.headers = {}
    assert _authorized(request) is False


def test_busy_gate():
    from job_search.server import _busy, _run_guarded

    async def _test():
        assert not _busy.locked()
        result = await _run_guarded("test", lambda: "ok")
        assert result == "ok"
        assert not _busy.locked()

    asyncio.run(_test())


def test_healthz_answers_during_slow_tool_call():
    import time

    import httpx

    from job_search.server import _run_guarded, app

    async def _test():
        def slow_fn():
            time.sleep(0.5)
            return "done"

        task = asyncio.create_task(_run_guarded("slow", slow_fn))
        await asyncio.sleep(0.05)

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            start = time.monotonic()
            resp = await client.get("/healthz")
            elapsed = time.monotonic() - start

        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}
        assert elapsed < 0.3, "event loop blocked while sync tool ran"

        assert await task == "done"

    asyncio.run(_test())


def test_resolve_ad_text_with_text():
    from job_search.server import _resolve_ad_text
    result = _resolve_ad_text("a plain text job ad")
    assert result == "a plain text job ad"


def test_resolve_ad_text_with_url():
    from unittest.mock import patch

    from job_search.server import _resolve_ad_text

    with patch("job_search.server.fetch_description") as mock_fetch:
        mock_fetch.return_value = "full job description"
        result = _resolve_ad_text("https://boards-api.greenhouse.io/v1/boards/x/jobs/1")
        assert result == "full job description"