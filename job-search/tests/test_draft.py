"""Test the drafting crew guardrails."""

from unittest.mock import MagicMock, patch

from job_search.draft import _check_claims, _pick_variant, draft_application

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


def test_placeholder_kept_is_ok():
    draft = "Salary: [[YOU FILL]] is fine"
    issues = _check_claims(draft, {})
    assert issues == []


def test_filled_slot_within_marker_detected():
    draft = "Salary: [[YOU FILL: 100k]] per year"
    issues = _check_claims(draft, {})
    assert len(issues) >= 1
    assert any("filled slot" in i for i in issues)


def test_slot_replaced_entirely_detected():
    draft = "Salary: 100k per year\nRight to work: yes\nNotice: 1 month"
    issues = _check_claims(draft, {})
    assert len(issues) >= 1
    assert any("missing placeholder" in i or "slot filled" in i for i in issues)


def test_all_placeholders_present_is_ok():
    draft = (
        "Salary: [[YOU FILL]]\n"
        "Right to work: [[YOU FILL]]\n"
        "Notice: [[YOU FILL]]\n"
        "Availability: [[YOU FILL]]"
    )
    issues = _check_claims(draft, {})
    assert issues == []


def test_rejected_when_slots_filled():
    fake_draft = "## CV summary\nSkip\n\nSalary: 100k"
    with patch("job_search.draft.read_profile", return_value={
        "target_titles": [], "target_seniority": [], "target_locations": [],
        "remote_policy": "remote", "cv_general_file": "general.docx",
    }), patch(
        "job_search.draft.read_cv",
        return_value=("cv body text", {"source": "general.docx"}),
    ):
        with patch("job_search.draft.list_cv_variants", return_value=[
            {"variant": "general", "file": "general.docx"},
        ]):
            with patch("job_search.draft.Crew") as mock_crew:
                mock_instance = MagicMock()
                mock_instance.kickoff.return_value = fake_draft
                mock_crew.return_value = mock_instance

                result = draft_application(AI_AD, role_id="test-123")
                assert result["rejected"] is True
                assert result["draft"] == ""


def test_clean_draft_accepted():
    clean = (
        "## CV summary\nExperienced...\n\n"
        "Salary: [[YOU FILL]]\n"
        "Right to work: [[YOU FILL]]\n"
        "Notice: [[YOU FILL]]\n"
        "Availability: [[YOU FILL]]"
    )
    with patch("job_search.draft.read_profile", return_value={
        "target_titles": [], "target_seniority": [], "target_locations": [],
        "remote_policy": "remote", "cv_general_file": "general.docx",
    }), patch(
        "job_search.draft.read_cv",
        return_value=("cv body text", {"source": "general.docx"}),
    ):
        with patch("job_search.draft.list_cv_variants", return_value=[
            {"variant": "general", "file": "general.docx"},
        ]):
            with patch("job_search.draft.Crew") as mock_crew:
                mock_instance = MagicMock()
                mock_instance.kickoff.return_value = clean
                mock_crew.return_value = mock_instance

                result = draft_application(AI_AD, role_id="test-456")
                assert "rejected" not in result or not result["rejected"]
                assert result["draft"] == clean