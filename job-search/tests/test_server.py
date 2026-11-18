"""Test the job-search MCP server: auth, busy gate, tool annotations."""

import asyncio


def _capture_writes(target: dict):
    def _write(role_id, draft, role):
        target.update(role_id=role_id, draft=draft, role=role)
        return "ok"

    return _write


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


def test_derive_role_id_pasted_text():
    import re

    from job_search.server import derive_role_id

    ad = "Director of Platform Engineering at Acme Corp\n\nSome description."
    role_id = derive_role_id(ad)
    assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*-[0-9a-f]{8}", role_id)
    assert role_id.startswith("acme-corp-director-of-platform-engineering-")
    assert len(role_id) <= 69


def test_derive_role_id_url_company():
    from job_search.server import derive_role_id

    url = "https://api.lever.co/v0/postings/acmecorp/abc123"
    ad = "Director of Platform Engineering\n\nFull description"
    role_id = derive_role_id(ad, url)
    assert role_id.startswith("acmecorp-director-of-platform-engineering-")


def test_derive_role_id_stable():
    from job_search.server import derive_role_id

    ad = "Director of Platform Engineering at Acme Corp\n\nSome description."
    assert derive_role_id(ad) == derive_role_id(ad)


def test_draft_result_pasted_text_derives_slug(monkeypatch):
    import re

    from job_search import server as srv

    ad = "Director of Platform Engineering at Acme Corp\n" + "".join(
        f"requirement {i} involves platform engineering\n" for i in range(300)
    )
    assert len(ad) > 10_000

    monkeypatch.setattr(
        srv,
        "_draft_application",
        lambda ad: {"cv_variant": "general", "cv_file": "cv/general.md", "draft": "draft text"},
    )
    written = {}
    monkeypatch.setattr(srv, "write_draft_and_role", _capture_writes(written))

    result = srv._draft_result(ad)
    role_id = written["role_id"]
    assert f"job-search/drafts/{role_id}.md" in result
    assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*-[0-9a-f]{8}", role_id)
    assert len(role_id) <= 69
    assert "requirement" not in role_id
    assert "status: drafted" in written["role"]
    assert "company: \"Acme Corp\"" in written["role"]
    assert "title: \"Director of Platform Engineering\"" in written["role"]


def test_draft_result_url_derives_slug(monkeypatch):
    import re

    from job_search import server as srv

    url = "https://api.lever.co/v0/postings/acmecorp/abc123"
    ad = "Director of Platform Engineering\n\nFull description"

    monkeypatch.setattr(srv, "_resolve_ad_text", lambda t: ad)
    monkeypatch.setattr(
        srv,
        "_draft_application",
        lambda ad: {"cv_variant": "general", "cv_file": "cv/general.md", "draft": "draft text"},
    )
    captured = {}
    monkeypatch.setattr(srv, "write_draft_and_role", _capture_writes(captured))

    srv._draft_result(url)
    role_id = captured["role_id"]
    assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*-[0-9a-f]{8}", role_id)
    assert role_id.startswith("acmecorp-director-of-platform-engineering-")
    assert "status: drafted" in captured["role"]
    assert "source: \"lever\"" in captured["role"]
    assert "url: \"https://api.lever.co/v0/postings/acmecorp/abc123\"" in captured["role"]


def test_pipeline_summary_handles_quoted_and_unquoted_dates(monkeypatch, tmp_path):
    import asyncio

    from job_search import server as srv
    from job_search import vault

    roles_dir = tmp_path / "job-search" / "roles"
    roles_dir.mkdir(parents=True)
    (roles_dir / "overdue.md").write_text(
        "---\ncompany: Acme\ntitle: Engineer\nstatus: shortlisted\n"
        "next_action_date: 2020-01-01\n---\n"
    )
    (roles_dir / "future.md").write_text(
        '---\ncompany: Beta\ntitle: Manager\nstatus: applied\n'
        'next_action_date: "2099-01-01"\n---\n'
    )
    (roles_dir / "none.md").write_text(
        "---\ncompany: Gamma\ntitle: Lead\nstatus: interviewing\n---\n"
    )

    monkeypatch.setattr(vault, "VAULT_READ_ROOT", tmp_path)

    out = asyncio.run(srv.pipeline_summary())
    assert "Overdue follow-ups (1)" in out
    assert "Acme" in out