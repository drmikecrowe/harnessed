"""compute_recipe_hash + the `harnessed build` reconciliation it feeds.

Covers: the hash is stable, changes when any file in a recipe's closure or the stack's own
stack.yaml changes, `paths.list_catalog_stacks` dedupes across catalog roots (user wins), and
`_reconcile_stacks` only rebuilds stacks whose image label doesn't match the current hash.
Also covers: service-only edits (entrypoint.sh, service.yaml, Dockerfile) move the hash
regardless of whether the recipe or stack.yaml changed (harnessed-p0t).
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


def _write_stack(root: Path, name: str, *, recipes: list[str], services: list[str] | None = None) -> Path:
    stack_dir = root / "stacks" / name
    stack_dir.mkdir(parents=True)
    content = f"name: {name}\nrecipes: {recipes}\n"
    if services is not None:
        content += f"services: {services}\n"
    (stack_dir / "stack.yaml").write_text(content)
    return stack_dir


def _write_service(root: Path, name: str, *, entrypoint: str = "#!/bin/sh\nexec serve\n") -> Path:
    """Write a minimal service directory under ``root/services/<name>/``.

    Returns the service directory path.
    """
    svc_dir = root / "services" / name
    svc_dir.mkdir(parents=True)
    (svc_dir / "service.yaml").write_text(
        f"name: {name}\nimage: {name}:latest\nport: 9000\n"
    )
    (svc_dir / "Dockerfile").write_text(f"FROM scratch\nCOPY entrypoint.sh /\n")
    (svc_dir / "entrypoint.sh").write_text(entrypoint)
    return svc_dir


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

    # --- service closure (harnessed-p0t) ---

    def test_changes_when_stack_service_entrypoint_changes(self, tmp_path):
        """A service-only edit must move the hash even when the stack.yaml is untouched."""
        recipe = _write_recipe(tmp_path, "r1")
        svc_dir = _write_service(tmp_path, "svc1")
        stack_yaml = _write_stack(tmp_path, "s1", recipes=["r1"], services=["svc1"]) / "stack.yaml"
        before = compute_recipe_hash(stack_yaml, [recipe])

        (svc_dir / "entrypoint.sh").write_text("#!/bin/sh\nexec serve --changed\n")

        assert compute_recipe_hash(stack_yaml, [recipe]) != before

    def test_changes_when_stack_service_dockerfile_changes(self, tmp_path):
        recipe = _write_recipe(tmp_path, "r1")
        svc_dir = _write_service(tmp_path, "svc1")
        stack_yaml = _write_stack(tmp_path, "s1", recipes=["r1"], services=["svc1"]) / "stack.yaml"
        before = compute_recipe_hash(stack_yaml, [recipe])

        (svc_dir / "Dockerfile").write_text("FROM ubuntu:24.04\nCOPY entrypoint.sh /\n")

        assert compute_recipe_hash(stack_yaml, [recipe]) != before

    def test_changes_when_recipe_service_file_changes(self, tmp_path):
        """Service referenced via recipe.services (non-MCP sidecar) also moves the hash."""
        svc_dir = _write_service(tmp_path, "svc2")
        recipe = Recipe(
            name="r1",
            root=_write_recipe(tmp_path, "r1").root,
            services=["svc2"],
        )
        stack_yaml = _write_stack(tmp_path, "s1", recipes=["r1"]) / "stack.yaml"
        before = compute_recipe_hash(stack_yaml, [recipe])

        (svc_dir / "entrypoint.sh").write_text("#!/bin/sh\nexec serve --new\n")

        assert compute_recipe_hash(stack_yaml, [recipe]) != before

    def test_missing_service_dir_does_not_raise(self, tmp_path):
        """A service name with no matching directory is silently skipped (service may be external)."""
        recipe = _write_recipe(tmp_path, "r1")
        stack_yaml = _write_stack(tmp_path, "s1", recipes=["r1"], services=["nonexistent-svc"]) / "stack.yaml"

        # Should not raise, just skip the missing service
        compute_recipe_hash(stack_yaml, [recipe])


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

    def test_generic_list_catalog_unifies_non_stack_kind(self, tmp_path, monkeypatch):
        # The user overlay (a.k.a. catalog/recipes.local) and the repo catalog are one namespace:
        # a name in both appears once, and overlay-only names are included.
        user_root = tmp_path / "user"
        repo_root = tmp_path / "repo"
        _write_recipe(user_root, "shared")
        _write_recipe(user_root, "overlay-only")
        _write_recipe(repo_root, "shared")
        _write_recipe(repo_root, "repo-only")

        monkeypatch.setattr(paths, "catalog_roots", lambda: [user_root, repo_root])

        assert paths.list_catalog("recipes") == ["overlay-only", "repo-only", "shared"]


class TestReconcileStacks:
    def test_rebuilds_only_stale_or_missing_stacks(self, monkeypatch, tmp_path):
        import subprocess as _subprocess

        r1 = _write_recipe(tmp_path, "r1")
        _write_stack(tmp_path, "up-to-date", recipes=["r1"])
        _write_stack(tmp_path, "stale", recipes=["r1"])
        _write_stack(tmp_path, "missing-image", recipes=["r1"])

        # Mock podman images to return three previously-built images.
        image_list = "harnessed-claude-up-to-date\nharnessed-claude-stale\nharnessed-claude-missing-image\n"
        monkeypatch.setattr(
            launcher.subprocess, "run",
            lambda *a, **k: _subprocess.CompletedProcess(a, 0, stdout=image_list),
        )
        monkeypatch.setattr(
            launcher, "load_stack_with_recipes",
            lambda root, name, strict=False: (None, [r1]),
        )

        current_hash = compute_recipe_hash(tmp_path / "stacks" / "up-to-date" / "stack.yaml", [r1])
        image_hashes = {
            ("up-to-date", "claude"): current_hash,
            ("stale", "claude"): "old-hash",
            ("missing-image", "claude"): None,
        }
        monkeypatch.setattr(launcher, "_built_image_hash", lambda rt, name, harness: image_hashes.get((name, harness)))

        built = []
        monkeypatch.setattr(launcher, "_build_stack", lambda rt, name, harness, root, strict: built.append(name))

        launcher._reconcile_stacks("podman", tmp_path, strict=True)

        assert sorted(built) == ["missing-image", "stale"]

    def test_no_stacks_is_a_noop(self, monkeypatch, tmp_path):
        import subprocess as _subprocess

        monkeypatch.setattr(
            launcher.subprocess, "run",
            lambda *a, **k: _subprocess.CompletedProcess(a, 0, stdout=""),
        )
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
        assert launcher._built_image_hash("podman", "some-stack", "claude") == "abc123"

    def test_returns_none_when_image_missing(self, monkeypatch):
        monkeypatch.setattr(
            launcher.subprocess, "run",
            lambda *a, **k: subprocess.CompletedProcess(a, 1, stdout=""),
        )
        assert launcher._built_image_hash("podman", "some-stack", "claude") is None

    def test_returns_none_when_label_absent(self, monkeypatch):
        monkeypatch.setattr(
            launcher.subprocess, "run",
            lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout="\n"),
        )
        assert launcher._built_image_hash("podman", "some-stack", "claude") is None
