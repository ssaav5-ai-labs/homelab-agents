"""Test the job-alert parser with LinkedIn digest and generic formats."""


from job_search.parse import (
    parse_alert,
    parse_generic,
    parse_linkedin_digest,
)
from tests.fixtures import extract_text_plain, read_fixture


def test_is_hiring():
    plain = extract_text_plain(read_fixture("is-hiring.eml"))
    records = parse_linkedin_digest(plain)
    assert len(records) == 2
    assert records[0].title == "Forward Deployed Engineer (Remote)"
    assert records[0].company == "Joblet-AI"
    assert records[0].location == "Ireland"
    assert records[0].source == "linkedin"
    assert records[0].source_id == "4490242142"
    assert records[1].title == "AI Research Engineer (Remote)"
    assert records[1].source_id == "4490225302"


def test_actively_recruiting():
    plain = extract_text_plain(read_fixture("actively-recruiting.eml"))
    records = parse_linkedin_digest(plain)
    assert len(records) == 1
    assert records[0].title == "Director, Technical Product Management"
    assert records[0].company == "McKesson"
    assert records[0].location == "Cork"
    assert records[0].source_id == "4483332841"


def test_multi_job_digest():
    plain = extract_text_plain(read_fixture("multi-job-digest.eml"))
    records = parse_linkedin_digest(plain)
    assert len(records) == 2
    assert records[0].title == "Director of Platform Engineering"
    assert records[0].company == "GoodCo"
    assert records[0].location == "Dublin"
    assert records[0].source_id == "11111111"
    assert records[1].title == "Senior SRE Manager"
    assert records[1].company == "OtherCorp"
    assert records[1].location == "Remote"
    assert records[1].source_id == "22222222"


def test_single_job_no_location():
    plain = extract_text_plain(read_fixture("single-job-no-location.eml"))
    records = parse_linkedin_digest(plain)
    assert len(records) == 1
    assert records[0].title == "DevOps Lead"
    assert records[0].company == "SoloCorp"
    assert records[0].source_id == "33333333"


def test_parse_alert_prefers_digest_for_linkedin():
    plain = extract_text_plain(read_fixture("is-hiring.eml"))
    records = parse_alert(plain, "text/plain")
    assert len(records) == 2
    assert all(r.source == "linkedin" for r in records)


def test_empty_digest():
    records = parse_linkedin_digest("")
    assert records == []


def test_no_jobs_in_digest():
    records = parse_linkedin_digest("Your job alert for IT\n\n\n\n\n")
    assert records == []


def test_generic_with_url():
    records = parse_generic("New job! Title: SRE Lead\nCompany: TechCorp\nhttps://example.com/jobs/abc123")
    assert len(records) >= 1
    assert records[0].url == "https://example.com/jobs/abc123"
    assert records[0].source == "generic"


def test_generic_no_url():
    records = parse_generic("Hello World")
    assert records == []


def test_parse_alert_falls_back_to_generic_for_non_linkedin():
    records = parse_alert("New job! Title: DevOps\nhttps://greenhouse.io/jobs/123", "text/plain")
    assert len(records) >= 1
    assert records[0].source == "generic"