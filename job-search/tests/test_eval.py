from pathlib import Path

from job_search.eval import _extract_roles

FIXTURE = Path(__file__).parent / "fixtures" / "eval-rated.md"


def test_extract_two_roles():
    roles = _extract_roles(FIXTURE)
    assert len(roles) == 2

    r1 = roles[0]
    assert r1[0] == "1"
    assert r1[1] == 85
    assert len(r1[2]) > 100
    assert "Senior Director of Coffee Infrastructure" in r1[2]
    assert "Acme Corp" in r1[2]
    assert "example.com/jobs/1" in r1[3]

    r2 = roles[1]
    assert r2[0] == "2"
    assert r2[1] == 15
    assert len(r2[2]) > 50
    assert "Junior Barista Intern" in r2[2]
    assert "Tiny Cafe Ltd" in r2[2]
    assert "example.com/jobs/2" in r2[3]


def test_empty_ad_text():
    """A role with no body between metadata and --- must have ad_len=0."""
    text = "## 1. Ghost Role\n- **My score:** 50\n- **Link:** https://example.com/jobs/9\n---\n"
    import tempfile

    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
        f.write(text)
        f.flush()
        roles = _extract_roles(Path(f.name))
    Path(f.name).unlink()
    assert len(roles) == 1
    assert roles[0][2] == ""
    assert roles[0][1] == 50