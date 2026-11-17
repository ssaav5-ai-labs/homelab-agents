"""Test the drafting crew guardrails."""

from unittest.mock import patch

from job_search.draft import FILLED_SLOT_RE, _check_claims, _pick_variant

AI_AD = "Looking for a Director of AI Platform to lead our ML/LLM/agent platform team."
GENERAL_AD = "Looking for a Director of SRE to lead our infrastructure team."


def test_pick_variant_ai():
    with patch("job_search.draft.read_profile", return_value={"cv_ai_use_when": "AI or ML roles"}):
        variant = _pick_variant(AI_AD)
        assert variant == "ai"


def test_pick_variant_general():
    with patch("job_search.draft.read_profile", return_value={"cv_ai_use_when": "AI or ML roles"}):
        variant = _pick_variant(GENERAL_AD)
        assert variant == "general"


def test_filled_slot_detection():
    draft = "Salary: [[YOU FILL]] is fine"
    filled = FILLED_SLOT_RE.findall(draft)
    assert len(filled) == 0  # correctly kept as placeholder

    bad_draft = "Salary: 100k per year"
    filled_bad = _check_claims(bad_draft, {})
    assert filled_bad == []  # no fill slots to detect


def test_filled_slot_rejected():
    draft = "Salary: [[YOU FILL]]"  # correctly left as placeholder
    filled = _check_claims(draft, {})
    assert filled == []  # not filled, so OK