from sre_crews import tools


def test_find_runbook_matches(tmp_path, monkeypatch):
    domains = tmp_path / "docs" / "domains" / "k3s"
    domains.mkdir(parents=True)
    (domains / "runbook-node-down.md").write_text("# Node down\nnode down runbook content")

    monkeypatch.setattr(tools, "HANDBOOK_ROOT", str(tmp_path))
    result = tools.find_runbook("node down")
    assert "runbook-node-down.md" in result
    assert "runbook content" in result


def test_find_runbook_no_match(tmp_path, monkeypatch):
    domains = tmp_path / "docs" / "domains" / "k3s"
    domains.mkdir(parents=True)
    (domains / "runbook-node-down.md").write_text("node down")

    monkeypatch.setattr(tools, "HANDBOOK_ROOT", str(tmp_path))
    result = tools.find_runbook("nonexistent topic")
    assert "No runbook matched" in result


def test_find_runbook_caps_at_two(tmp_path, monkeypatch):
    domains = tmp_path / "docs" / "domains"
    (domains / "a").mkdir(parents=True)
    (domains / "b").mkdir(parents=True)
    (domains / "c").mkdir(parents=True)
    (domains / "a" / "runbook-1.md").write_text("needle")
    (domains / "b" / "runbook-2.md").write_text("needle")
    (domains / "c" / "runbook-3.md").write_text("needle")

    monkeypatch.setattr(tools, "HANDBOOK_ROOT", str(tmp_path))
    result = tools.find_runbook("needle")
    assert result.count("runbook-") == 2
