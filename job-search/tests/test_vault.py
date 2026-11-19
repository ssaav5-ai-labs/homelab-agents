import pytest

from job_search.vault import (
    _git_env,
    _validate_path,
    read_processed_state,
    read_recent_digests,
    read_roles,
    render_processed_state,
    to_date,
)


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


def test_git_env_sets_scoped_safe_directory():
    from job_search.vault import VAULT_WORK_ROOT

    env = _git_env()
    assert env["GIT_CONFIG_COUNT"] == "1"
    assert env["GIT_CONFIG_KEY_0"] == "safe.directory"
    assert env["GIT_CONFIG_VALUE_0"] == str(VAULT_WORK_ROOT)
    assert "*" not in env["GIT_CONFIG_VALUE_0"]


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


def test_commit_in_foreign_owned_repo(monkeypatch, tmp_path):
    import os
    import shutil
    import subprocess

    import job_search.vault as vault

    if os.geteuid() == 0:
        pytest.skip("root bypasses git's dubious-ownership check")
    if shutil.which("sudo") is None:
        pytest.skip("sudo required to create a foreign-owned repo")

    repo = tmp_path / "repo"
    repo.mkdir()
    git = ["git", "-C", str(repo)]

    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(git + ["config", "user.email", "test@example.com"], check=True)
    subprocess.run(git + ["config", "user.name", "test"], check=True)
    (repo / "a.md").write_text("one")
    subprocess.run(git + ["add", "a.md"], check=True)
    subprocess.run(git + ["commit", "-qm", "init"], check=True)

    subprocess.run(
        ["sudo", "-n", "chown", "-R", f"root:{os.getgid()}", str(repo)], check=True
    )
    subprocess.run(["sudo", "-n", "chmod", "-R", "g+w", str(repo)], check=True)

    monkeypatch.setattr(vault, "VAULT_WORK_ROOT", repo)

    bare_env = {
        "HOME": str(tmp_path),
        "PATH": os.environ.get("PATH", ""),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_AUTHOR_NAME": "test",
        "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "test",
        "GIT_COMMITTER_EMAIL": "test@example.com",
    }
    denied = subprocess.run(
        git + ["log", "-1"], capture_output=True, text=True, env=bare_env
    )
    assert denied.returncode != 0
    assert "dubious ownership" in denied.stderr

    env = vault._git_env()
    (repo / "b.md").write_text("two")
    subprocess.run(git + ["add", "b.md"], capture_output=True, text=True, env=env, check=True)
    subprocess.run(
        git + ["commit", "-qm", "add b"], capture_output=True, text=True, env=env, check=True
    )

    log = subprocess.run(
        git + ["log", "-1", "--format=%s"], capture_output=True, text=True, env=env
    )
    assert log.returncode == 0
    assert log.stdout.strip() == "add b"


def test_render_processed_state_prunes_old_entries():

    today = "2026-11-19"
    state = {
        "aaabbb": "2026-10-01",
        "ccc111": today,
        "ddd222": "2026-10-15",
        "malformed": "",
    }
    result = render_processed_state(state, today)
    lines = result.strip().split("\n") if result.strip() else []
    hashes = [line.split()[0] for line in lines]
    assert "ccc111" in hashes
    assert "aaabbb" not in hashes
    assert "ddd222" not in hashes
    assert "malformed" not in hashes


def test_render_processed_state_sorted_newest_first():
    today = "2026-11-19"
    state = {"key1": "2026-11-15", "key2": "2026-11-19", "key3": "2026-11-10"}
    result = render_processed_state(state, today)
    lines = result.strip().split("\n")
    dates = [line.split()[1] for line in lines]
    assert dates == ["2026-11-19", "2026-11-15", "2026-11-10"]


def test_read_processed_state_parses_hash_date(monkeypatch, tmp_path):
    import job_search.vault as vault

    state_dir = tmp_path / "job-search" / "state"
    state_dir.mkdir(parents=True)
    (state_dir / "processed.txt").write_text(
        "abc123 2026-11-18\n"
        "def456 2026-11-19\n"
        "\n"
        "  \n"
        "bad_line\n"
        "ghi789 2026-11-17\n"
    )

    monkeypatch.setattr(vault, "VAULT_READ_ROOT", tmp_path)

    result = read_processed_state()
    assert result["abc123"] == "2026-11-18"
    assert result["def456"] == "2026-11-19"
    assert result["ghi789"] == "2026-11-17"
    assert "bad_line" in result


def test_read_processed_state_empty_if_missing(monkeypatch, tmp_path):
    import job_search.vault as vault

    monkeypatch.setattr(vault, "VAULT_READ_ROOT", tmp_path)
    assert read_processed_state() == {}


def test_read_recent_digests_returns_last_n_days(monkeypatch, tmp_path):
    from datetime import date, timedelta

    import job_search.vault as vault

    today = date.today()
    digests_dir = tmp_path / "job-search" / "digests"
    digests_dir.mkdir(parents=True)

    expected = {}
    for i in range(20):
        date_str = (today - timedelta(days=i)).strftime("%Y-%m-%d")
        content = f"content for {date_str}"
        (digests_dir / f"{date_str}.md").write_text(content)
        expected[date_str] = content

    monkeypatch.setattr(vault, "VAULT_READ_ROOT", tmp_path)
    monkeypatch.setattr(vault, "date", type("MockDate", (), {"today": lambda: today}))

    result = read_recent_digests(7)
    assert len(result) == 7
    for date_str, content in result.items():
        assert date_str in expected
        assert content == expected[date_str]


def test_read_recent_digests_skips_missing_dates(monkeypatch, tmp_path):
    from datetime import date, timedelta

    import job_search.vault as vault

    today = date.today()
    digests_dir = tmp_path / "job-search" / "digests"
    digests_dir.mkdir(parents=True)

    one_day = (today - timedelta(days=1)).strftime("%Y-%m-%d")
    (digests_dir / f"{one_day}.md").write_text("yesterday")

    monkeypatch.setattr(vault, "VAULT_READ_ROOT", tmp_path)
    monkeypatch.setattr(vault, "date", type("MockDate", (), {"today": lambda: today}))

    result = read_recent_digests(5)
    assert len(result) == 1
    assert one_day in result
