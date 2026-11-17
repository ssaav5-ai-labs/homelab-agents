

from job_search.parse import (
    parse_alert,
    parse_generic,
    parse_linkedin_alert,
)

LINKEDIN_ALERT = """
<html><body>
<h3>Senior SRE Manager</h3>
<p>at <span>ExampleCorp</span></p>
<a href="https://www.linkedin.com/jobs/view/12345678/">Senior SRE Manager</a>
</body></html>
"""

LINKEDIN_ALERT_MULTI = """
<html><body>
<h3>Director of Platform</h3>
<a href="https://www.linkedin.com/jobs/view/111/">Director of Platform</a>
<h3>Head of SRE</h3>
<a href="https://www.linkedin.com/jobs/view/222/">Head of SRE</a>
</body></html>
"""

GENERIC_TEXT = """
New job alert:
Title: Senior Platform Engineer
Company: TechCo
https://example.com/jobs/abc123
"""


def test_parse_linkedin_single():
    records = parse_linkedin_alert(LINKEDIN_ALERT)
    assert len(records) >= 1


def test_parse_linkedin_source():
    records = parse_linkedin_alert(LINKEDIN_ALERT)
    record = records[0]
    assert record.source == "linkedin"
    assert record.source_id == "12345678"


def test_parse_linkedin_multi():
    records = parse_linkedin_alert(LINKEDIN_ALERT_MULTI)
    assert len(records) >= 2
    ids = {r.source_id for r in records}
    assert ids == {"111", "222"}


def test_parse_generic_extracts_urls():
    records = parse_generic(GENERIC_TEXT)
    assert len(records) >= 1
    assert records[0].url == "https://example.com/jobs/abc123"


def test_parse_alert_prefers_linkedin():
    records = parse_alert(LINKEDIN_ALERT)
    assert len(records) >= 1
    assert records[0].source == "linkedin"


def test_parse_empty_string():
    records = parse_alert("")
    assert records == []