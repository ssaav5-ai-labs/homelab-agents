import pytest

from job_search.vault import _validate_path


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