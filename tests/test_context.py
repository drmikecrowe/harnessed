"""Tests for context.py — what a stack loads every session, and its duplicates and leaks."""

from pathlib import Path

from harnessed.context import collect, problems


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def _skill(config: Path, rel: str, name: str, description: str = "does a thing") -> None:
    _write(config / "skills" / rel / "SKILL.md", f"---\nname: {name}\ndescription: {description}\n---\nbody\n")


def test_collects_memory_and_skill_descriptions(tmp_path):
    config = tmp_path / "config"
    _write(config / "CLAUDE.md", "x" * 40)
    _write(config / "rules" / "floor" / "RULE.md", "y" * 80)
    _skill(config, "ponytail", "ponytail", "d" * 20)
    items = {(it.kind, it.name): it.tokens for it in collect(config)}
    assert items == {("memory", "CLAUDE.md"): 10, ("memory", "RULE.md"): 20, ("skill", "ponytail"): 5}


def test_clean_profile_has_no_problems(tmp_path):
    config = tmp_path / "config"
    _write(config / "rules" / "a.md", "a")
    _skill(config, "ponytail", "ponytail")
    assert problems(collect(config, tmp_path / "home" / "project")) == []


def test_one_skill_name_in_two_places_is_a_problem(tmp_path):
    # The plugin-bundled copy is namespaced, so no build-time name check can see it.
    config = tmp_path / "config"
    _skill(config, "simple-english", "simple-english")
    _skill(config, "se-creator/skills/simple-english", "simple-english")
    [found] = problems(collect(config))
    assert found.startswith("skill 'simple-english' is installed 2 times")


def test_skill_in_a_symlinked_plugin_dir_is_seen(tmp_path):
    # A host launch links plugin dirs into the config dir; the walk must follow them.
    plugin = tmp_path / "checkout" / "spec-evidence"
    _skill(plugin.parent, "spec-evidence/skills/story-readiness", "story-readiness")
    config = tmp_path / "config"
    (config / "skills").mkdir(parents=True)
    (config / "skills" / "spec-evidence").symlink_to(tmp_path / "checkout" / "skills" / "spec-evidence")
    assert [it.name for it in collect(config) if it.kind == "skill"] == ["story-readiness"]


def test_ancestor_memory_is_a_leak_and_a_duplicate(tmp_path):
    home = tmp_path / "home"
    project = home / "code" / "repo"
    project.mkdir(parents=True)
    _write(home / ".claude" / "rules" / "react.md", "same")
    _write(home / "CLAUDE.md", "template")
    _write(project / "CLAUDE.md", "the project's own file is not a leak")
    config = tmp_path / "config"
    _write(config / "rules" / "react.md", "same")
    found = problems(collect(config, project))
    assert f"loaded from outside the stack: {home / 'CLAUDE.md'}" in found
    assert f"loaded from outside the stack: {home / '.claude' / 'rules' / 'react.md'}" in found
    assert any(p.startswith("same content loaded twice") for p in found)
    assert not any(str(project / "CLAUDE.md") in p for p in found)


def test_dangling_rule_symlink_is_not_a_leak(tmp_path):
    home = tmp_path / "home"
    project = home / "repo"
    project.mkdir(parents=True)
    (home / ".claude" / "rules").mkdir(parents=True)
    (home / ".claude" / "rules" / "gone.md").symlink_to(home / "missing.md")
    assert problems(collect(tmp_path / "config", project)) == []


def test_symlink_loop_terminates(tmp_path):
    config = tmp_path / "config"
    _skill(config, "ponytail", "ponytail")
    (config / "skills" / "ponytail" / "loop").symlink_to(config / "skills")
    assert [it.name for it in collect(config) if it.kind == "skill"] == ["ponytail"]
