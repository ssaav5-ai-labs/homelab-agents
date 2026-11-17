

from job_search.score import SCORE_PROMPT, _extract_json


def test_extract_json_valid():
    result = _extract_json(
        '{"score": 85, "why": "good fit", "gaps": "none", "must_ask": "when start?"}'
    )
    assert result == {"score": 85, "why": "good fit", "gaps": "none", "must_ask": "when start?"}


def test_extract_json_with_markdown():
    result = _extract_json('Here is the result:\n```json\n{"score": 70}\n```')
    assert result is not None
    assert result.get("score") == 70


def test_extract_json_invalid():
    result = _extract_json("not json at all")
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