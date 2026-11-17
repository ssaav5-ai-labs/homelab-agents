from job_search.score import (
    SCORE_PROMPT,
    ScoreError,
    _extract_json,
    score_role,
)


def test_extract_json_valid():
    result = _extract_json(
        '{"score": 85, "why": "good fit", "gaps": "none", "must_ask": "when start?"}'
    )
    assert result == {"score": 85, "why": "good fit", "gaps": "none", "must_ask": "when start?"}


def test_extract_json_with_markdown():
    result = _extract_json('Here is the result:\n```json\n{"score": 70}\n```')
    assert result is not None
    assert result.get("score") == 70


def test_extract_json_fenced():
    result = _extract_json('```json\n{"score": 72, "why": "ok", "gaps": "", "must_ask": ""}\n```')
    assert result is not None
    assert result.get("score") == 72


def test_extract_json_string_score():
    result = _extract_json(
        '```json\n{"score": "78", "why": "fit", "gaps": "", "must_ask": ""}\n```'
    )
    assert result is not None
    assert result["score"] == "78"


def test_extract_json_invalid():
    result = _extract_json("not json at all")
    assert result is None


def test_extract_json_truncated():
    result = _extract_json('{"score": 85, "why": "great match", "gaps": "none"')
    assert result is None


def test_extract_json_empty():
    result = _extract_json("")
    assert result is None


def test_score_prompt_contains_weights():
    prompt = SCORE_PROMPT.format(
        weight_role_scope=30,
        weight_technical_fit=25,
        weight_leadership_fit=20,
        weight_location_remote=15,
        weight_company_domain=10,
        target_titles="Director, Head of",
        target_seniority="Director, Head of, Senior Manager",
        target_locations="Dublin, remote Ireland",
        remote_policy="remote-only",
        shortlist_threshold=70,
        ad_text="test ad",
    )
    assert "30" in prompt
    assert "25" in prompt
    assert "remote-only" in prompt
    assert "test ad" in prompt
    assert "untrusted data" in prompt.lower()


def test_score_error_on_empty_reply(monkeypatch):
    calls = []

    class FakeLLM:
        def call(self, messages):
            calls.append(messages)
            return ""

    monkeypatch.setattr("job_search.score.make_scoring_llm", lambda: FakeLLM())
    monkeypatch.setattr(
        "job_search.score.read_profile",
        lambda: {
            "target_titles": ["Director"],
            "target_seniority": ["Director"],
            "target_locations": ["Dublin"],
            "remote_policy": "remote",
        },
    )

    try:
        score_role("some ad text")
        raise AssertionError("expected ScoreError")
    except ScoreError:
        pass
    assert len(calls) == 2


def test_score_error_on_truncated_json(monkeypatch):
    calls = []

    class FakeLLM:
        def call(self, messages):
            calls.append(messages)
            return '{"score": 85, "why": "good", "gaps": null'

    monkeypatch.setattr("job_search.score.make_scoring_llm", lambda: FakeLLM())
    monkeypatch.setattr(
        "job_search.score.read_profile",
        lambda: {
            "target_titles": ["Director"],
            "target_seniority": ["Director"],
            "target_locations": ["Dublin"],
            "remote_policy": "remote",
        },
    )

    try:
        score_role("some ad text")
        raise AssertionError("expected ScoreError")
    except ScoreError:
        pass
    assert len(calls) == 2


def test_score_error_on_missing_score(monkeypatch):
    calls = []

    class FakeLLM:
        def call(self, messages):
            calls.append(messages)
            return '{"why": "great", "gaps": "none", "must_ask": "when?"}'

    monkeypatch.setattr("job_search.score.make_scoring_llm", lambda: FakeLLM())
    monkeypatch.setattr(
        "job_search.score.read_profile",
        lambda: {
            "target_titles": ["Director"],
            "target_seniority": ["Director"],
            "target_locations": ["Dublin"],
            "remote_policy": "remote",
        },
    )

    try:
        score_role("some ad text")
        raise AssertionError("expected ScoreError")
    except ScoreError:
        pass
    assert len(calls) == 2


def test_score_success(monkeypatch):
    import json

    calls = []

    class FakeLLM:
        def call(self, messages):
            calls.append(messages)
            return json.dumps(
                {"score": 85, "why": "great fit", "gaps": "none", "must_ask": "when start?"}
            )

    monkeypatch.setattr("job_search.score.make_scoring_llm", lambda: FakeLLM())
    monkeypatch.setattr(
        "job_search.score.read_profile",
        lambda: {
            "target_titles": ["Director"],
            "target_seniority": ["Director"],
            "target_locations": ["Dublin"],
            "remote_policy": "remote",
        },
    )

    result = score_role("some ad text")
    assert result["score"] == 85
    assert result["why"] == "great fit"
    assert len(calls) == 1


def test_score_success_fenced(monkeypatch):
    import json

    calls = []

    class FakeLLM:
        def call(self, messages):
            calls.append(messages)
            return (
                '```json\n'
                + json.dumps(
                    {"score": 72, "why": "ok", "gaps": "none", "must_ask": "when?"}
                )
                + '\n```'
            )

    monkeypatch.setattr("job_search.score.make_scoring_llm", lambda: FakeLLM())
    monkeypatch.setattr(
        "job_search.score.read_profile",
        lambda: {
            "target_titles": ["Director"],
            "target_seniority": ["Director"],
            "target_locations": ["Dublin"],
            "remote_policy": "remote",
        },
    )

    result = score_role("some ad text")
    assert result["score"] == 72
    assert len(calls) == 1


def test_score_success_string_score(monkeypatch):
    calls = []

    class FakeLLM:
        def call(self, messages):
            calls.append(messages)
            return '{"score": "78", "why": "ok", "gaps": "", "must_ask": ""}'

    monkeypatch.setattr("job_search.score.make_scoring_llm", lambda: FakeLLM())
    monkeypatch.setattr(
        "job_search.score.read_profile",
        lambda: {
            "target_titles": ["Director"],
            "target_seniority": ["Director"],
            "target_locations": ["Dublin"],
            "remote_policy": "remote",
        },
    )

    result = score_role("some ad text")
    assert result["score"] == 78
    assert len(calls) == 1