"""compute_recipe_hash + the `harnessed build` reconciliation it feeds.

Covers: the hash is stable, changes when any file in a recipe's closure or the stack's own
stack.yaml changes, `paths.list_catalog_stacks` dedupes across catalog roots (user wins), and
`_reconcile_stacks` only rebuilds stacks whose image label doesn't match the current hash.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from harnessed import launcher, paths
from harnessed.assemble import compute_recipe_hash
from harnessed.schema import Recipe


def _write_recipe(root: Path, name: str, *, dockerfile: str = "RUN echo hi\n") -> Recipe:
    recipe_dir = root / "recipes" / name
    recipe_dir.mkdir(parents=True)
    (recipe_dir / "recipe.yaml").write_text(f"name: {name}\n")
    (recipe_dir / "Dockerfile").write_text(dockerfile)
    return Recipe(name=name, root=recipe_dir)


def _write_stack(root: Path, name: str, *, recipes: list[str]) -> Path:
    stack_dir = root / "stacks" / name
    stack_dir.mkdir(parents=True)
    (stack_dir / "stack.yaml").write_text(f"name: {name}\nrecipes: {recipes}\n")
    return stack_dir


class TestComputeRecipeHash:
    def test_stable_for_unchanged_inputs(self, tmp_path):
        recipe = _write_recipe(tmp_path, "r1")
        stack_yaml = _write_stack(tmp_path, "s1", recipes=["r1"]) / "stack.yaml"

        assert compute_recipe_hash(stack_yaml, [recipe]) == compute_recipe_hash(stack_yaml, [recipe])

    def test_changes_when_recipe_file_changes(self, tmp_path):
        recipe = _write_recipe(tmp_path, "r1")
        stack_yaml = _write_stack(tmp_path, "s1", recipes=["r1"]) / "stack.yaml"
        before = compute_recipe_hash(stack_yaml, [recipe])

        (recipe.root / "Dockerfile").write_text("RUN echo changed\n")

        assert compute_recipe_hash(stack_yaml, [recipe]) != before

    def test_changes_when_stack_yaml_changes(self, tmp_path):
        recipe = _write_recipe(tmp_path, "r1")
        stack_dir = _write_stack(tmp_path, "s1", recipes=["r1"])
        stack_yaml = stack_dir / "stack.yaml"
        before = compute_recipe_hash(stack_yaml, [recipe])

        stack_yaml.write_text("name: s1\nrecipes: ['r1']\npermissions: yolo\n")

        assert compute_recipe_hash(stack_yaml, [recipe]) != before

    def test_recipe_order_does_not_affect_hash(self, tmp_path):
        r1 = _write_recipe(tmp_path, "r1")
        r2 = _write_recipe(tmp_path, "r2")
        stack_yaml = _write_stack(tmp_path, "s1", recipes=["r1", "r2"]) / "stack.yaml"

        assert compute_recipe_hash(stack_yaml, [r1, r2]) == compute_recipe_hash(stack_yaml, [r2, r1])


class TestListCatalogStacks:
    def test_dedupes_user_overlay_over_repo(self, tmp_path, monkeypatch):
        user_root = tmp_path / "user"
        repo_root = tmp_path / "repo"
        _write_stack(user_root, "shared", recipes=[])
        _write_stack(repo_root, "shared", recipes=[])
        _write_stack(repo_root, "repo-only", recipes=[])

        monkeypatch.setattr(paths, "catalog_roots", lambda: [user_root, repo_root])

        assert paths.list_catalog_stacks() == ["repo-only", "shared"]

    def test_empty_when_no_stacks_dir(self, tmp_path, monkeypatch):
        monkeypatch.setattr(paths, "catalog_roots", lambda: [tmp_path / "nope"])
        assert paths.list_catalog_stacks() == []


class TestReconcileStacks:
    def test_rebuilds_only_stale_or_missing_stacks(self, monkeypatch, tmp_path):
        r1 = _write_recipe(tmp_path, "r1")
        _write_stack(tmp_path, "up-to-date", recipes=["r1"])
        _write_stack(tmp_path, "stale", recipes=["r1"])
        _write_stack(tmp_path, "missing-image", recipes=["r1"])

        monkeypatch.setattr(paths, "list_catalog_stacks", lambda: ["missing-image", "stale", "up-to-date"])
        monkeypatch.setattr(
            launcher, "load_stack_with_recipes",
            lambda root, name, strict: (None, [r1]),
        )

        current_hash = compute_recipe_hash(tmp_path / "stacks" / "up-to-date" / "stack.yaml", [r1])
        image_hashes = {"up-to-date": current_hash, "stale": "old-hash", "missing-image": None}
        monkeypatch.setattr(launcher, "_built_image_hash", lambda rt, name: image_hashes[name])

        built = []
        monkeypatch.setattr(launcher, "_build_stack", lambda rt, name, root, strict: built.append(name))

        launcher._reconcile_stacks("podman", tmp_path, strict=True)

        assert sorted(built) == ["missing-image", "stale"]

    def test_no_stacks_is_a_noop(self, monkeypatch, tmp_path):
        monkeypatch.setattr(paths, "list_catalog_stacks", lambda: [])
        built = []
        monkeypatch.setattr(launcher, "_build_stack", lambda *a, **k: built.append(a))

        launcher._reconcile_stacks("podman", None, strict=True)

        assert built == []


class TestBuiltImageHash:
    def test_returns_label_value(self, monkeypatch):
        monkeypatch.setattr(
            launcher.subprocess, "run",
            lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout="abc123\n"),
        )
        assert launcher._built_image_hash("podman", "some-stack") == "abc123"

    def test_returns_none_when_image_missing(self, monkeypatch):
        monkeypatch.setattr(
            launcher.subprocess, "run",
            lambda *a, **k: subprocess.CompletedProcess(a, 1, stdout=""),
        )
        assert launcher._built_image_hash("podman", "some-stack") is None

    def test_returns_none_when_label_absent(self, monkeypatch):
        monkeypatch.setattr(
            launcher.subprocess, "run",
            lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout="\n"),
        )
        assert launcher._built_image_hash("podman", "some-stack") is None
