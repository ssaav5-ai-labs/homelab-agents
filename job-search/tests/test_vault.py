import pytest

from job_search.vault import _git_env, _validate_path, read_roles, to_date


def test_valid_path():
    _validate_path("job-search/roles/test.md")


def test_path_escape():
    with pytest.raises(ValueError):
        _validate_path("job-search/../../etc/passwd")


def test_path_not_under_prefix():
    with pytest.raises(ValueError):
        _validate_path("other/file.md")


def test_path_root_prefix_only():
    with pytest.raises(ValueError):
        _validate_path("../job-search/roles/test.md")


def test_git_env_ssh_command_uses_rw_key_and_known_hosts():
    env = _git_env()
    assert "/etc/vault-keys/rw" in env["GIT_SSH_COMMAND"]
    assert "-o IdentitiesOnly=yes" in env["GIT_SSH_COMMAND"]
    assert "-o UserKnownHostsFile=/etc/ssh/known_hosts" in env["GIT_SSH_COMMAND"]


def test_git_env_sets_identity():
    env = _git_env()
    assert env["GIT_AUTHOR_NAME"] == "job-search"
    assert env["GIT_AUTHOR_EMAIL"] == "job-search@localhost"
    assert env["GIT_COMMITTER_NAME"] == "job-search"
    assert env["GIT_COMMITTER_EMAIL"] == "job-search@localhost"


def test_to_date_unquoted_date():
    from datetime import date

    assert to_date(date(2026, 11, 18)) == date(2026, 11, 18)


def test_to_date_quoted_string():
    from datetime import date

    assert to_date("2026-11-18") == date(2026, 11, 18)


def test_to_date_missing_or_empty():
    assert to_date(None) is None
    assert to_date("") is None


def test_read_roles_normalizes_dates(monkeypatch, tmp_path):
    from datetime import date

    import job_search.vault as vault

    roles_dir = tmp_path / "job-search" / "roles"
    roles_dir.mkdir(parents=True)
    (roles_dir / "unquoted.md").write_text(
        "---\ncompany: Acme\ntitle: Engineer\n"
        "applied: 2026-11-01\nnext_action_date: 2026-11-20\n---\n"
    )
    (roles_dir / "quoted.md").write_text(
        '---\ncompany: Beta\ntitle: Manager\n'
        'applied: "2026-11-02"\nnext_action_date: "2026-11-10"\n---\n'
    )
    (roles_dir / "missing.md").write_text(
        "---\ncompany: Gamma\ntitle: Lead\n---\n"
    )

    monkeypatch.setattr(vault, "VAULT_READ_ROOT", tmp_path)

    roles = {r["_id"]: r for r in read_roles()}
    assert roles["unquoted"]["applied"] == date(2026, 11, 1)
    assert roles["unquoted"]["next_action_date"] == date(2026, 11, 20)
    assert roles["quoted"]["applied"] == date(2026, 11, 2)
    assert roles["quoted"]["next_action_date"] == date(2026, 11, 10)
    assert "applied" not in roles["missing"]
    assert "next_action_date" not in roles["missing"]