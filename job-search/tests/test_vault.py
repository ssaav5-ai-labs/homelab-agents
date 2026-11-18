import pytest

from job_search.vault import _git_env, _validate_path


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