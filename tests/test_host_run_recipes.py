"""`harnessed host-run` — accept a recipe set (--recipe) without authoring a stack.yaml (harnessed-cta)."""
from __future__ import annotations

from typer.testing import CliRunner

from harnessed import launcher

runner = CliRunner()


class TestHostRunRecipeXOR:
    """stack XOR --recipe: exactly one must be given."""

    def test_stack_and_recipe_are_mutually_exclusive(self, monkeypatch, tmp_path):
        """Must fail on the EXCLUSIVITY check, not incidentally. _launch_host is stubbed so a
        nonzero exit cannot come from it rejecting 'my-stack' as a missing project directory, and
        the message is asserted so the test cannot pass for an unrelated reason."""
        launched: list = []
        monkeypatch.setattr(launcher.dynstack.paths, "generated_catalog_root", lambda: tmp_path)
        monkeypatch.setattr(
            launcher, "_launch_host", lambda *a, **k: launched.append(a)
        )
        result = runner.invoke(launcher.app, ["host-run", "claude", "--stack", "my-stack", "--recipe", "serena"])
        assert result.exit_code != 0
        assert "not both" in result.output
        assert launched == [], "nothing may be launched when the invocation is rejected"
        assert not list(tmp_path.glob("stacks/*/stack.yaml")), "nothing may be minted either"

    def test_neither_stack_nor_recipe_runs_the_extends_baseline(self, monkeypatch, tmp_path):
        """Composing nothing is a launch, not an error: the `default` baseline runs as-is, and
        nothing is minted for it — it is an authored stack, so there is no manifest to write."""
        calls: list = []
        monkeypatch.setattr(launcher.dynstack.paths, "generated_catalog_root", lambda: tmp_path)
        monkeypatch.setattr(
            launcher, "_launch_host",
            lambda stack, harness, path, *, rm=False, extra=None, create_aoe_only=False, no_strict_mcp=False, aoe_group=None, aoe_title=None, exec_mode=False: calls.append(stack),
        )
        result = runner.invoke(launcher.app, ["host-run", "claude"])
        assert result.exit_code == 0, result.output
        assert calls == ["default"]
        assert not list(tmp_path.glob("stacks/*/stack.yaml")), "the baseline is authored, not minted"

    def test_extends_names_the_baseline_that_runs(self, monkeypatch, tmp_path):
        """`--extends` is the one knob that selects it, so a non-default baseline runs alone too."""
        calls: list = []
        monkeypatch.setattr(launcher.dynstack.paths, "generated_catalog_root", lambda: tmp_path)
        monkeypatch.setattr(
            launcher, "_launch_host",
            lambda stack, harness, path, *, rm=False, extra=None, create_aoe_only=False, no_strict_mcp=False, aoe_group=None, aoe_title=None, exec_mode=False: calls.append(stack),
        )
        result = runner.invoke(launcher.app, ["host-run", "claude", "--extends", "hostspike"])
        assert result.exit_code == 0, result.output
        assert calls == ["hostspike"]

    def test_no_extends_without_a_recipe_is_an_error(self, monkeypatch, tmp_path):
        """Inherit from nothing AND compose nothing leaves nothing to run — the one shape a bare
        invocation cannot be read as."""
        launched: list = []
        monkeypatch.setattr(launcher.dynstack.paths, "generated_catalog_root", lambda: tmp_path)
        monkeypatch.setattr(launcher, "_launch_host", lambda *a, **k: launched.append(a))
        result = runner.invoke(launcher.app, ["host-run", "claude", "--no-extends"])
        assert result.exit_code != 0
        assert "--no-extends" in result.output
        assert launched == [], "nothing may be launched when the invocation is rejected"

    def test_stack_alone_still_works(self, monkeypatch):
        """Existing authored-stack path is unchanged."""
        calls: list = []
        monkeypatch.setattr(
            launcher, "_launch_host",
            lambda stack, harness, path, *, rm=False, extra=None, create_aoe_only=False, no_strict_mcp=False, aoe_group=None, aoe_title=None, exec_mode=False: calls.append(stack),
        )
        result = runner.invoke(launcher.app, ["host-run", "claude", "--stack", "hostspike"])
        assert result.exit_code == 0, result.output
        assert calls == ["hostspike"]


class TestHostRunRecipeMinting:
    """When --recipe is given: mint a generated stack, then call _launch_host. No _build_stack."""

    def test_recipes_mint_and_then_call_launch_host(self, monkeypatch, tmp_path):
        calls: dict[str, object] = {}
        monkeypatch.setattr(launcher.dynstack.paths, "generated_catalog_root", lambda: tmp_path)
        monkeypatch.setattr(
            launcher, "_launch_host",
            lambda stack, harness, path, *, rm=False, extra=None, create_aoe_only=False, no_strict_mcp=False, aoe_group=None, aoe_title=None, exec_mode=False: calls.__setitem__(
                "launched", (stack, harness)
            ),
        )
        result = runner.invoke(
            launcher.app,
            ["host-run", "claude", "--recipe", "superpowers", "--recipe", "serena"],
        )
        assert result.exit_code == 0, result.output
        assert calls["launched"] == ("default.serena.superpowers", "claude")

    def test_recipe_defaults_to_extending_default(self, monkeypatch, tmp_path):
        monkeypatch.setattr(launcher.dynstack.paths, "generated_catalog_root", lambda: tmp_path)
        monkeypatch.setattr(launcher, "_launch_host", lambda *a, **k: None)
        runner.invoke(launcher.app, ["host-run", "claude", "--recipe", "serena"])
        text = (tmp_path / "stacks" / "default.serena" / "stack.yaml").read_text()
        assert "extends: default" in text

    def test_no_extends_drops_the_base(self, monkeypatch, tmp_path):
        monkeypatch.setattr(launcher.dynstack.paths, "generated_catalog_root", lambda: tmp_path)
        monkeypatch.setattr(launcher, "_launch_host", lambda *a, **k: None)
        runner.invoke(launcher.app, ["host-run", "claude", "--recipe", "serena", "--no-extends"])
        assert "extends:" not in (tmp_path / "stacks" / "serena" / "stack.yaml").read_text()

    def test_service_is_carried_into_the_minted_manifest(self, monkeypatch, tmp_path):
        monkeypatch.setattr(launcher.dynstack.paths, "generated_catalog_root", lambda: tmp_path)
        monkeypatch.setattr(launcher, "_launch_host", lambda *a, **k: None)
        runner.invoke(
            launcher.app,
            ["host-run", "claude", "--recipe", "serena", "--service", "beads-server"],
        )
        manifests = list((tmp_path / "stacks").glob("*/stack.yaml"))
        assert len(manifests) == 1
        assert "beads-server" in manifests[0].read_text()

    def test_no_build_step_on_recipe_path(self, monkeypatch, tmp_path):
        """Unlike `run`, host-run never needs a container image — _build_stack must NOT be called."""
        monkeypatch.setattr(launcher.dynstack.paths, "generated_catalog_root", lambda: tmp_path)
        monkeypatch.setattr(launcher, "_launch_host", lambda *a, **k: None)

        def boom(*_a, **_k):
            raise AssertionError("_build_stack must not be called from host-run with --recipe")

        monkeypatch.setattr(launcher, "_build_stack", boom)
        result = runner.invoke(launcher.app, ["host-run", "claude", "--recipe", "serena"])
        assert result.exit_code == 0, result.output

    def test_services_identity_is_part_of_the_derived_name(self, monkeypatch, tmp_path):
        """Services are passed to BOTH derive_name and mint, so the name encodes the full identity."""
        monkeypatch.setattr(launcher.dynstack.paths, "generated_catalog_root", lambda: tmp_path)
        captured: dict = {}
        monkeypatch.setattr(
            launcher, "_launch_host",
            lambda stack, harness, path, *, rm=False, extra=None, create_aoe_only=False, no_strict_mcp=False, aoe_group=None, aoe_title=None, exec_mode=False: captured.__setitem__("stack", stack),
        )

        runner.invoke(launcher.app, ["host-run", "claude", "--recipe", "serena"])
        name_without = captured.get("stack")
        runner.invoke(
            launcher.app,
            ["host-run", "claude", "--recipe", "serena", "--service", "beads-server"],
        )
        name_with = captured.get("stack")
        assert name_without != name_with, (
            "a different --service must produce a different stack name"
        )

    def test_the_project_path_is_a_positional_in_the_recipe_form_too(self, monkeypatch, tmp_path):
        """One grammar for both stack sources — the path is the same positional either way.

        This is what the flag-named stack bought. The path used to need a dedicated `--path`
        option, because with the stack in the first positional slot Typer (which binds by
        DECLARATION order, not meaning) could not tell `~/proj` from a stack name. That forced a
        rejects-all-positionals rule on the recipe form, and it still let `host-run <stack>
        --recipe X` launch the generated stack with the authored name demoted to a path, exit 0.
        With the stack at `--stack`, the remaining positional has exactly one meaning.
        """
        captured: dict = {}
        monkeypatch.setattr(launcher.dynstack.paths, "generated_catalog_root", lambda: tmp_path)
        monkeypatch.setattr(
            launcher, "_launch_host",
            lambda stack, harness, path, *, rm=False, extra=None, create_aoe_only=False, no_strict_mcp=False, aoe_group=None, aoe_title=None, exec_mode=False: captured.update(
                stack=stack, path=path
            ),
        )
        proj = tmp_path / "proj"
        result = runner.invoke(
            launcher.app, ["host-run", "claude", str(proj), "--recipe", "serena"]
        )
        assert result.exit_code == 0, result.output
        assert captured == {"stack": "default.serena", "path": str(proj)}

    def test_a_failed_launch_removes_a_manifest_this_run_minted(self, monkeypatch, tmp_path):
        """Same ownership rule as the container backend, which had it and this one did not.

        Host mode has no build to fail, but `_launch_host` assembles in-process, so a bad recipe
        set raises here instead. The orphan it would leave behind shows up in `harnessed list` and
        no GC reclaims it — volume-gc keys on volumes, and a stack that never launched owns none.
        """
        monkeypatch.setattr(launcher.dynstack.paths, "generated_catalog_root", lambda: tmp_path)

        def boom(*_a, **_k):
            raise RuntimeError("assembly failed")

        monkeypatch.setattr(launcher, "_launch_host", boom)
        runner.invoke(launcher.app, ["host-run", "claude", "--recipe", "serena"])
        assert not (tmp_path / "stacks" / "default.serena").exists()

    def test_a_failed_launch_keeps_a_preexisting_manifest(self, monkeypatch, tmp_path):
        """Deleting an already-working stack because today's launch broke is collateral damage."""
        monkeypatch.setattr(launcher.dynstack.paths, "generated_catalog_root", lambda: tmp_path)
        monkeypatch.setattr(launcher, "_launch_host", lambda *a, **k: None)
        runner.invoke(launcher.app, ["host-run", "claude", "--recipe", "serena"])  # mints it
        assert (tmp_path / "stacks" / "default.serena" / "stack.yaml").is_file(), "setup failed"

        def boom(*_a, **_k):
            raise RuntimeError("assembly failed")

        monkeypatch.setattr(launcher, "_launch_host", boom)
        runner.invoke(launcher.app, ["host-run", "claude", "--recipe", "serena"])
        assert (tmp_path / "stacks" / "default.serena" / "stack.yaml").is_file()

    def test_create_aoe_only_keeps_the_manifest_its_row_points_at(self, monkeypatch, tmp_path):
        """`--create-aoe-only` succeeds by RAISING: `_aoe_register` ends it with `typer.Exit(0)`.

        That unwinds through the orphan-cleanup handler like any failure, so a naive `except
        Exception` deletes the manifest the row it just wrote names in its recorded command —
        manufacturing exactly the dead-on-arrival row the container path builds ahead of
        registering to avoid.
        """
        import inspect

        # The premise, pinned so it cannot drift out from under the handler below: that is really
        # how `--create-aoe-only` reports success. (Driving the real `_aoe_register` from here
        # would need a resolvable catalog — assembly runs first, by ab3b060 — which is a different
        # test's job.)
        assert "raise typer.Exit(0)" in inspect.getsource(launcher._aoe_register)

        monkeypatch.setattr(launcher.dynstack.paths, "generated_catalog_root", lambda: tmp_path)

        def registered_and_stop(*_a, **_k):
            raise launcher.typer.Exit(0)

        monkeypatch.setattr(launcher, "_launch_host", registered_and_stop)
        result = runner.invoke(
            launcher.app, ["host-run", "claude", "--recipe", "serena", "--create-aoe-only"]
        )
        assert result.exit_code == 0, result.output
        assert (tmp_path / "stacks" / "default.serena" / "stack.yaml").is_file(), (
            "the registered row names this stack; deleting it leaves the row dead on arrival"
        )

    def test_a_nonzero_exit_still_cleans_up(self, monkeypatch, tmp_path):
        """The Exit(0) carve-out must not swallow real failures.

        `_launch_host` rejects a non-claude harness with `typer.Exit(1)`, and it does so AFTER the
        mint — so this path still owns the orphan.
        """
        monkeypatch.setattr(launcher.dynstack.paths, "generated_catalog_root", lambda: tmp_path)

        def exit_one(*_a, **_k):
            raise launcher.typer.Exit(1)

        monkeypatch.setattr(launcher, "_launch_host", exit_one)
        runner.invoke(launcher.app, ["host-run", "claude", "--recipe", "serena"])
        assert not (tmp_path / "stacks" / "default.serena").exists()

    def test_mint_error_surfaces_as_nonzero_exit(self, monkeypatch, tmp_path):
        """An invalid recipe name that derive_name / mint rejects → clean error, not a traceback."""
        monkeypatch.setattr(launcher.dynstack.paths, "generated_catalog_root", lambda: tmp_path)
        monkeypatch.setattr(launcher, "_launch_host", lambda *a, **k: None)
        # A recipe name that sanitizes to the empty string (all unsafe chars) triggers ValueError.
        result = runner.invoke(launcher.app, ["host-run", "claude", "--recipe", "***"])
        assert result.exit_code != 0
