"""`harnessed build` dispatch — how a stack's `harnesses:` list drives what gets built.

Three forms, all covered here with `_build_stack` stubbed out (the actual assemble/podman work is
covered elsewhere — what matters here is WHICH (stack, harness) pairs get handed to it):

* `build <stack> <harness>` → that one pair
* `build <stack>`           → every harness in the stack's `harnesses:` list
* `build`                   → declared pairs + previously-built pairs, rebuilt when stale
"""

import re
import subprocess

import pytest
from typer.testing import CliRunner

from harnessed import launcher
from support import patch_all

runner = CliRunner()

_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def plain(output: str) -> str:
    """rich colourizes and hard-wraps to the terminal width — strip both so an error message can be
    asserted on as the single line it logically is."""
    return " ".join(_ANSI.sub("", output).split())


@pytest.fixture
def root(tmp_path):
    """A --root catalog with a stack that declares two harnesses and one that declares none."""
    stacks = tmp_path / "stacks"
    (stacks / "multi").mkdir(parents=True)
    (stacks / "multi" / "stack.yaml").write_text(
        "name: multi\nrecipes: []\nharnesses: [claude, omp]\n"
    )
    (stacks / "single").mkdir(parents=True)
    (stacks / "single" / "stack.yaml").write_text("name: single\nrecipes: []\n")
    return tmp_path


@pytest.fixture
def built(monkeypatch):
    """Record every (stack, harness) `build` hands to `_build_stack`, doing no real work."""
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        launcher, "_build_stack",
        lambda rt, stack, harness, root=None, **kw: calls.append((stack, harness)),
    )
    monkeypatch.setattr(launcher, "_ensure_local_catalog_links", lambda: None)
    monkeypatch.setattr(launcher, "_ensure_docs_wiki_clone", lambda: None)
    patch_all(monkeypatch, "_runtime", lambda: "podman")
    return calls


class TestBuildStackHarnessArgument:
    def test_explicit_harness_builds_only_that_pair(self, root, built):
        result = runner.invoke(launcher.app, ["build", "multi", "claude", "--root", str(root)])
        assert result.exit_code == 0, result.output
        assert built == [("multi", "claude")]

    def test_omitted_harness_fans_out_to_declared_harnesses(self, root, built):
        result = runner.invoke(launcher.app, ["build", "multi", "--root", str(root)])
        assert result.exit_code == 0, result.output
        assert built == [("multi", "claude"), ("multi", "omp")]

    def test_omitted_harness_without_declaration_errors(self, root, built):
        result = runner.invoke(launcher.app, ["build", "single", "--root", str(root)])
        assert result.exit_code == 1
        assert "harness is required" in plain(result.output)
        assert built == []

    def test_unknown_harness_errors(self, root, built):
        result = runner.invoke(launcher.app, ["build", "multi", "bogus", "--root", str(root)])
        assert result.exit_code == 1
        assert "unsupported harness 'bogus'" in plain(result.output)
        assert built == []

    def test_unknown_stack_errors(self, root, built):
        result = runner.invoke(launcher.app, ["build", "nope", "--root", str(root)])
        assert result.exit_code == 1
        assert "unknown stack 'nope'" in plain(result.output)
        assert built == []


class TestBareBuildReconcile:
    """A bare `harnessed build` sweeps DECLARED pairs (even with no image yet) plus every pair that
    has been built before — so authoring a stack with `harnesses:` is enough to have it provisioned,
    while a stack that declares none stays opt-in (only rebuilt once explicitly named at least once).
    """

    @pytest.fixture(autouse=True)
    def _no_image_builds(self, monkeypatch):
        monkeypatch.setattr(launcher, "_build_images_cmd", lambda rt, force=False: None)
        # _reconcile_stacks builds the shared prerequisites (base + one agent image per harness in
        # scope) BEFORE fanning out to the workers. Stub them: this suite is about WHICH pairs get
        # dispatched, and the podman stub below only knows `images` and `inspect`.
        monkeypatch.setattr(launcher, "_build_base_image", lambda rt: None)
        monkeypatch.setattr(launcher, "_build_agent_image", lambda rt, harness: None)

    def _fake_podman(self, monkeypatch, *, images: str, hashes: dict[str, str]):
        """Stub `podman images` (built-image inventory) and `podman inspect` (recipe-hash label)."""
        def fake_run(cmd, **kwargs):
            if cmd[1] == "images":
                return subprocess.CompletedProcess(cmd, 0, stdout=images, stderr="")
            if cmd[1] == "inspect":
                image = cmd[-1]
                if image not in hashes:
                    return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="no such image")
                return subprocess.CompletedProcess(cmd, 0, stdout=hashes[image] + "\n", stderr="")
            raise AssertionError(f"unexpected command: {cmd}")

        monkeypatch.setattr(launcher.subprocess, "run", fake_run)

    def test_declared_pairs_build_even_with_no_existing_image(self, root, built, monkeypatch):
        self._fake_podman(monkeypatch, images="", hashes={})
        result = runner.invoke(launcher.app, ["build", "--root", str(root)])
        assert result.exit_code == 0, result.output
        # 'multi' declares [claude, omp]; 'single' declares none → not swept.
        assert built == [("multi", "claude"), ("multi", "omp")]

    def test_declared_pair_with_current_hash_is_skipped(self, root, built, monkeypatch):
        from harnessed.assemble import compute_recipe_hash
        from harnessed.schema import load_stack_with_recipes

        _, recipes = load_stack_with_recipes(root, "multi", strict=True)
        current = compute_recipe_hash(root / "stacks" / "multi" / "stack.yaml", recipes)
        self._fake_podman(
            monkeypatch,
            images="",
            hashes={
                "harnessed-claude-multi:latest": current,
                "harnessed-omp-multi:latest": current,
            },
        )
        result = runner.invoke(launcher.app, ["build", "--root", str(root)])
        assert result.exit_code == 0, result.output
        assert built == [], "a declared pair whose image is already current must not rebuild"

    def test_previously_built_undeclared_stack_still_reconciles(self, root, built, monkeypatch):
        # 'single' declares no harnesses, but has a stale built image → still swept, as before.
        self._fake_podman(
            monkeypatch,
            images="harnessed-claude-single\n",
            hashes={"harnessed-claude-single:latest": "stale"},
        )
        result = runner.invoke(launcher.app, ["build", "--root", str(root)])
        assert result.exit_code == 0, result.output
        assert ("single", "claude") in built
