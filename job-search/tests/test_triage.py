"""Test triage sender filtering and text extraction."""



from job_search.triage import _allowed_senders, _extract
from tests.fixtures import read_fixture


def test_allowed_senders_default():
    senders = _allowed_senders()
    assert "jobalerts-noreply@linkedin.com" in senders


def test_allowed_senders_from_env(monkeypatch):
    monkeypatch.setenv("TRIAGE_ALLOWED_SENDERS",
                       "jobalerts-noreply@linkedin.com, jobs-noreply@linkedin.com")
    senders = _allowed_senders()
    assert "jobalerts-noreply@linkedin.com" in senders
    assert "jobs-noreply@linkedin.com" in senders


def test_extract_allows_linkedin_sender():
    raw = read_fixture("is-hiring.eml")
    result = _extract(raw)
    assert result is not None
    from_addr, plain, html = result
    assert "linkedin.com" in from_addr.lower()
    assert "Forward Deployed Engineer" in plain


def test_extract_rejects_unknown_sender():
    raw = read_fixture("spam.eml")
    result = _extract(raw)
    assert result is None


def test_extract_returns_plain_and_html():
    raw = read_fixture("is-hiring.eml")
    result = _extract(raw)
    assert result is not None
    _from_addr, plain, html = result
    assert len(plain) > 0
    assert "Joblet-AI" in plain


def test_triage_disabled_by_default():
    from job_search import triage
    assert not triage.ENABLED