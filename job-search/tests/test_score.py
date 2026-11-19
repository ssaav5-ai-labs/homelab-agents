import json

import litellm.exceptions as litellm_exc

from job_search.score import (
    _classify_gateway_error,
    _compute_score,
    _extract_json,
    _final_error,
    _parse_dealbreaker,
)


def test_extract_json_valid():
    result = _extract_json(
        '{"score": 85, "why": "good fit", "gaps": "none", "must_ask": "when start?"}'
    )
    assert result == {"score": 85, "why": "good fit", "gaps": "none", "must_ask": "when start?"}


def test_extract_json_fenced():
    result = _extract_json(
        '```json\n{"score": 72, "why": "ok", "gaps": "", "must_ask": ""}\n```'
    )
    assert result is not None
    assert result.get("score") == 72


def test_extract_json_invalid():
    result = _extract_json("not json at all")
    assert result is None


def test_extract_json_empty():
    result = _extract_json("")
    assert result is None


def test_parse_dealbreaker_no():
    triggered, quote = _parse_dealbreaker("no")
    assert not triggered
    assert quote == ""


def test_parse_dealbreaker_yes_with_quote():
    triggered, quote = _parse_dealbreaker(
        "yes reports to CTO who owns strategy, no team management"
    )
    assert triggered
    assert "reports to CTO" in quote


def test_parse_dealbreaker_empty():
    triggered, quote = _parse_dealbreaker("")
    assert not triggered
    assert quote == ""


def test_compute_score_perfect():
    criteria = {
        "scope_platform_sre": {"value": "yes", "quote": "Platform Engineering"},
        "people_leadership": {"value": "yes", "quote": "leads managers"},
        "strategy_ownership": {"value": "yes", "quote": "owns strategy"},
        "remote": {"value": "yes", "quote": "fully remote"},
        "ai_ml_scope": {"value": "yes", "quote": "AI platform"},
        "salary_vs_floor": {"value": "yes", "quote": "EUR 140k"},
    }
    dealbreakers = {"ic_with_manager_title": "no", "ops_only_no_platform": "no",
                    "legacy_onprem_only": "no", "product_eng_systems_internals": "no"}
    profile = {
        "scope_platform_sre": 20, "people_leadership": 20, "strategy_ownership": 15,
        "remote": 15, "ai_ml_scope": 15, "salary_vs_floor": 5, "seniority_fit": 10,
        "dealbreaker_cap": 40, "target_titles": ["Director"],
        "target_seniority": ["Director"],
    }
    score = _compute_score(criteria, dealbreakers, "Director, Platform Engineering", profile)
    assert score == 100


def test_compute_score_capped():
    criteria = {
        "scope_platform_sre": {"value": "yes", "quote": "platform"},
        "people_leadership": {"value": "yes", "quote": "leads"},
        "strategy_ownership": {"value": "yes", "quote": "strategy"},
        "remote": {"value": "yes", "quote": "remote"},
        "ai_ml_scope": {"value": "yes", "quote": "AI"},
        "salary_vs_floor": {"value": "yes", "quote": "120k"},
    }
    dealbreakers = {
        "ic_with_manager_title": "yes title is Head but no direct reports mentioned",
        "ops_only_no_platform": "no",
        "legacy_onprem_only": "no",
        "product_eng_systems_internals": "no",
    }
    profile = {
        "scope_platform_sre": 20, "people_leadership": 20, "strategy_ownership": 15,
        "remote": 15, "ai_ml_scope": 15, "salary_vs_floor": 5, "seniority_fit": 10,
        "dealbreaker_cap": 40, "target_titles": ["Head"],
        "target_seniority": ["Head of"],
    }
    score = _compute_score(criteria, dealbreakers, "Head of Platform", profile)
    assert score == 40


def test_compute_score_partial_and_unknown():
    criteria = {
        "scope_platform_sre": {"value": "yes", "quote": "SRE"},
        "people_leadership": {"value": "partial", "quote": "leads one team"},
        "strategy_ownership": {"value": "yes", "quote": "owns roadmap"},
        "remote": {"value": "unknown", "quote": "none"},
        "ai_ml_scope": {"value": "no", "quote": "none"},
        "salary_vs_floor": {"value": "unknown", "quote": "none"},
    }
    dealbreakers = {"ic_with_manager_title": "no", "ops_only_no_platform": "no",
                    "legacy_onprem_only": "no", "product_eng_systems_internals": "no"}
    profile = {
        "scope_platform_sre": 20, "people_leadership": 20, "strategy_ownership": 15,
        "remote": 15, "ai_ml_scope": 15, "salary_vs_floor": 5, "seniority_fit": 10,
        "dealbreaker_cap": 40, "target_titles": ["Director"],
        "target_seniority": ["Director"],
    }
    score = _compute_score(criteria, dealbreakers, "Director of SRE", profile)
    expected = 20 + (20 // 2) + 15 + (15 // 2) + 0 + (5 // 2) + 10
    assert score == expected


def test_score_role_success(monkeypatch):
    from job_search.score import score_role  # noqa: F811

    monkeypatch.setattr(
        "job_search.score.read_profile",
        lambda: {
            "scope_platform_sre": 20, "people_leadership": 20, "strategy_ownership": 15,
            "remote": 15, "ai_ml_scope": 15, "salary_vs_floor": 5, "seniority_fit": 10,
            "dealbreaker_cap": 40, "target_titles": ["Director"],
            "target_seniority": ["Director"],
        },
    )
    monkeypatch.setattr(
        "job_search.score._llm_call_with_backoff",
        lambda prompt: (json.dumps({
            "criteria": {
                "scope_platform_sre": {"value": "yes", "quote": "platform"},
                "people_leadership": {"value": "yes", "quote": "leads"},
                "strategy_ownership": {"value": "yes", "quote": "strategy"},
                "remote": {"value": "yes", "quote": "remote"},
                "ai_ml_scope": {"value": "yes", "quote": "AI"},
                "salary_vs_floor": {"value": "yes", "quote": "120k"},
            },
            "dealbreakers": {"ic_with_manager_title": "no", "ops_only_no_platform": "no",
                             "legacy_onprem_only": "no", "product_eng_systems_internals": "no"},
            "why": "great fit", "gaps": "none", "must_ask": "when start?",
        }), {"finish_reason": "stop", "completion_tokens": 200}),
    )
    result = score_role("some ad", title="Director, Platform Engineering")
    assert result["score"] == 100


def test_classify_budget_exceeded_error():
    exc = litellm_exc.BudgetExceededError(current_cost=0.5, max_budget=0.01)
    assert _classify_gateway_error(exc) == "budget_exceeded"


def test_classify_budget_in_400_body():
    exc = litellm_exc.BadRequestError(
        "budget has been exceeded", model="jobs-fast", llm_provider="openai"
    )
    assert _classify_gateway_error(exc) == "budget_exceeded"


def test_classify_401():
    exc = litellm_exc.AuthenticationError(
        "bad key", llm_provider="openai", model="jobs-fast"
    )
    assert _classify_gateway_error(exc) == "http_401"


def test_classify_402():
    exc = litellm_exc.PaymentRequiredError(
        "payment required", model="jobs-fast", llm_provider="openai"
    )
    assert _classify_gateway_error(exc) == "http_402"


def test_classify_retryable():
    assert _classify_gateway_error(RuntimeError("boom")) is None


def test_final_error_budget_message():
    assert "budget" in _final_error({"finish_reason": "budget_exceeded"})
    assert "ask the human" in _final_error({"finish_reason": "budget_exceeded"})


def test_final_error_401_message():
    assert "401" in _final_error({"finish_reason": "http_401"})


def test_final_error_402_message():
    assert "402" in _final_error({"finish_reason": "http_402"})


def test_final_error_unparseable():
    msg = _final_error({"finish_reason": "length", "completion_tokens": 0})
    assert "unparseable" in msg


def test_llm_backoff_no_retry_on_budget(monkeypatch):
    from job_search.score import _llm_call_with_backoff

    calls = []

    def fake_call(prompt, attempt=1):
        calls.append(attempt)
        raise litellm_exc.BudgetExceededError(current_cost=0.5, max_budget=0.01)

    monkeypatch.setattr("job_search.score._call_llm", fake_call)
    content, diag = _llm_call_with_backoff("prompt")
    assert content == ""
    assert diag["finish_reason"] == "budget_exceeded"
    assert calls == [1]


def test_score_role_budget_error(monkeypatch):
    import pytest

    from job_search.score import ScoreError, score_role

    monkeypatch.setattr(
        "job_search.score.read_profile",
        lambda: {
            "scope_platform_sre": 20, "people_leadership": 20, "strategy_ownership": 15,
            "remote": 15, "ai_ml_scope": 15, "salary_vs_floor": 5, "seniority_fit": 10,
            "dealbreaker_cap": 40, "target_titles": ["Director"],
            "target_seniority": ["Director"],
        },
    )
    monkeypatch.setattr(
        "job_search.score._llm_call_with_backoff",
        lambda prompt: ("", {"finish_reason": "budget_exceeded"}),
    )
    with pytest.raises(ScoreError, match="budget"):
        score_role("some ad")


def test_score_role_error_on_empty_content(monkeypatch):
    import pytest

    from job_search.score import ScoreError, score_role  # noqa: F811

    monkeypatch.setattr(
        "job_search.score.read_profile",
        lambda: {
            "scope_platform_sre": 20, "people_leadership": 20, "strategy_ownership": 15,
            "remote": 15, "ai_ml_scope": 15, "salary_vs_floor": 5, "seniority_fit": 10,
            "dealbreaker_cap": 40, "target_titles": ["Director"],
            "target_seniority": ["Director"],
        },
    )
    monkeypatch.setattr(
        "job_search.score._llm_call_with_backoff",
        lambda prompt: ("", {"finish_reason": "length", "completion_tokens": 0}),
    )
    with pytest.raises(ScoreError):
        score_role("some ad")