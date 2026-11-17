"""Test deterministic rules for role filtering."""

from unittest.mock import patch

from job_search.parse import RoleRecord
from job_search.rules import apply_rules

FAKE_PROFILE = {
    "target_titles": ["Director", "Head of", "Senior Manager"],
    "target_seniority": ["Director", "Head of", "Senior Manager"],
    "target_locations": ["Dublin, Ireland", "remote Ireland", "remote UK", "remote EU"],
    "remote_policy": "remote-only",
    "exclude_companies": [],
    "exclude_industries": [],
    "shortlist_threshold": 70,
    "daily_cap": 5,
}

ROLE_DUBLIN = RoleRecord(
    title="Director of Platform Engineering",
    company="GoodCo",
    location="Dublin, Ireland",
    url="https://example.com/jobs/1",
    source="linkedin",
    source_id="123",
)

ROLE_NY = RoleRecord(
    title="Senior SRE Manager",
    company="GoodCo",
    location="New York, NY",
    url="https://example.com/jobs/2",
    source="linkedin",
    source_id="456",
)

ROLE_JUNIOR = RoleRecord(
    title="Junior DevOps Engineer",
    company="GoodCo",
    location="Dublin, Ireland",
    source="linkedin",
    source_id="789",
)


def test_rules_pass_good_role():
    with patch("job_search.rules.read_profile", return_value=FAKE_PROFILE):
        with patch("job_search.rules.read_roles", return_value=[]):
            passed, skipped = apply_rules([ROLE_DUBLIN])
            assert len(passed) == 1
            assert len(skipped) == 0


def test_rules_skip_wrong_location():
    with patch("job_search.rules.read_profile", return_value=FAKE_PROFILE):
        with patch("job_search.rules.read_roles", return_value=[]):
            passed, skipped = apply_rules([ROLE_NY])
            assert len(passed) == 0
            assert len(skipped) == 1
            assert "location" in skipped[0]


def test_rules_skip_junior_title():
    with patch("job_search.rules.read_profile", return_value=FAKE_PROFILE):
        with patch("job_search.rules.read_roles", return_value=[]):
            passed, skipped = apply_rules([ROLE_JUNIOR])
            assert len(passed) == 0
            assert len(skipped) == 1
            assert "excluded title" in skipped[0]


def test_rules_skip_already_seen():
    with patch("job_search.rules.read_profile", return_value=FAKE_PROFILE):
        with patch("job_search.rules.read_roles", return_value=[{"source_id": "123"}]):
            passed, skipped = apply_rules([ROLE_DUBLIN])
            assert len(passed) == 0
            assert len(skipped) == 1
            assert "seen" in skipped[0]