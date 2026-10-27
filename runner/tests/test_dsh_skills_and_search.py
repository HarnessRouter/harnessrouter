"""dsh finds a setup's and a plugin package's skills, and offers no web search that calls DeepSeek's own API (2026-10-27).

dsh's skill tool loads only what its skill-filesystem provider found under its roots (<dshHome>/skills among them); the
runner writes skills to .harness/skills and .harness/plugins/<package>/skills, so every `skill` call answered "unknown or
no longer available". Its stock web_search provider posted to https://api.deepseek.com/anthropic/v1/messages with the
relay's placeholder key and was refused 401 on every search."""
import pathlib
import sys

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import dsh_driver  # noqa: E402


def _skill(root: pathlib.Path, name: str, body: str) -> None:
    (root / name).mkdir(parents=True, exist_ok=True)
    (root / name / "SKILL.md").write_text(f"---\nname: {name}\ndescription: {body}\n---\n{body}\n")


def test_setup_and_package_skills_land_where_dsh_looks(tmp_path):
    cwd, home = tmp_path / "ws", tmp_path / "home"
    _skill(cwd / ".harness" / "skills", "brand-voice", "the setup's own")
    _skill(cwd / ".harness" / "plugins" / "acme_designer" / "skills", "quality-brand-kit", "from the package")
    _skill(cwd / ".harness" / "plugins" / "acme_designer" / "skills", "brand-voice", "the package's, shadowed")
    _skill(cwd / ".harness" / "plugins" / "aaa_first" / "skills", "tool-knowledge", "another package")
    (cwd / ".harness" / "plugins" / "acme_designer" / "skills" / "not-a-skill").mkdir()       # no SKILL.md: skipped
    got = dsh_driver._install_skills(home, str(cwd))
    assert got == ["brand-voice", "tool-knowledge", "quality-brand-kit"]       # the setup first, then packages by name
    dest = home / ".dsh" / "skills"
    assert sorted(p.name for p in dest.iterdir()) == ["brand-voice", "quality-brand-kit", "tool-knowledge"]
    assert "the setup's own" in (dest / "brand-voice" / "SKILL.md").read_text()     # a setup's skill wins its name


def test_each_turn_rewrites_the_set(tmp_path):
    cwd, home = tmp_path / "ws", tmp_path / "home"
    _skill(cwd / ".harness" / "skills", "old-one", "x")
    dsh_driver._install_skills(home, str(cwd))
    (cwd / ".harness" / "skills" / "old-one" / "SKILL.md").unlink()
    _skill(cwd / ".harness" / "skills", "new-one", "y")
    assert dsh_driver._install_skills(home, str(cwd)) == ["new-one"]
    assert [p.name for p in (home / ".dsh" / "skills").iterdir()] == ["new-one"]       # a removed skill is gone


def test_no_harness_tree_installs_nothing(tmp_path):
    assert dsh_driver._install_skills(tmp_path / "home", str(tmp_path / "empty")) == []


def test_the_deepseek_web_search_row_is_off(tmp_path):
    path = dsh_driver._compose_patch(tmp_path / "home", [], cwd=str(tmp_path))
    entries = yaml.safe_load(pathlib.Path(path).read_text())
    assert {"id": "web-search-deepseek", "disabled": True} in entries
    # the tool itself is not registered: the provider row off alone still offered web_search, failing every call
    assert {"id": "tool-web", "config": {"search": False}} in entries
