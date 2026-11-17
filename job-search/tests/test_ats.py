from unittest.mock import patch

import pytest

from job_search.ats import AtsError, fetch_description


def test_linkedin_refused():
    result = fetch_description("https://www.linkedin.com/jobs/view/123")
    assert "LinkedIn" in result
    assert "can't be fetched" in result


def test_linkedin_subdomain_refused():
    result = fetch_description("https://linkedin.com/jobs/view/456")
    assert "LinkedIn" in result
    assert "can't be fetched" in result


def test_disallowed_host_raises():
    with pytest.raises(AtsError, match="not an allowed ATS API"):
        fetch_description("https://evil.com/api/job")


def test_allowed_host_greenhouse():
    with patch("job_search.ats.requests.get") as mock_get:
        mock_get.return_value.status_code = 200
        mock_get.return_value.headers = {}
        mock_get.return_value.iter_content.return_value = [b'{"content": "test"}']
        mock_get.return_value.raise_for_status = lambda: None
        result = fetch_description("https://boards-api.greenhouse.io/v1/boards/test/jobs/1")
        assert "test" in result


def test_allowed_host_lever():
    with patch("job_search.ats.requests.get") as mock_get:
        mock_get.return_value.status_code = 200
        mock_get.return_value.headers = {}
        mock_get.return_value.iter_content.return_value = [b'{"sections":[{"text":"lever job"}]}']
        mock_get.return_value.raise_for_status = lambda: None
        result = fetch_description("https://api.lever.co/v0/postings/test/1")
        assert "lever job" in result


def test_size_cap():
    with patch("job_search.ats.requests.get") as mock_get:
        mock_get.return_value.status_code = 200
        mock_get.return_value.headers = {"content-length": "2000000"}
        mock_get.return_value.raise_for_status = lambda: None
        with pytest.raises(AtsError, match="too large"):
            fetch_description("https://boards-api.greenhouse.io/v1/boards/x/jobs/1")