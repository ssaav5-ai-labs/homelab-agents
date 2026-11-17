

from job_search.llm import GATEWAY_HEADERS, make_llm


def test_message_redaction_header_set():
    assert "x-litellm-enable-message-redaction" in GATEWAY_HEADERS
    assert GATEWAY_HEADERS["x-litellm-enable-message-redaction"] == "true"


def test_make_llm_includes_headers(monkeypatch):
    monkeypatch.setenv("LAB_GATEWAY_URL", "http://gateway:4000")
    monkeypatch.setenv("JOBS_GATEWAY_KEY", "sk-test")
    llm = make_llm("jobs-fast")
    assert llm.api_key == "sk-test"