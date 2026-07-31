"""`harnessed host-run` — accept a recipe set (--recipe) without authoring a stack.yaml (harnessed-cta)."""
from __future__ import annotations

from typer.testing import CliRunner

from harnessed import launcher

runner = CliRunner()


class TestHostRunRecipeXOR:
    """stack XOR --recipe: exactly one must be given."""

    def test_stack_and_recipe_are_mutually_exclusive(self, monkeypatch, tmp_path):
        monkeypatch.setattr(launcher.dynstack.paths, "generated_catalog_root", lambda: tmp_path)
        result = runner.invoke(
            launcher.app, ["host-run", "my-stack", "--recipe", "serena"]
        )
        assert result.exit_code != 0

    def test_neither_stack_nor_recipe_is_an_error(self):
        result = runner.invoke(launcher.app, ["host-run"])
        assert result.exit_code != 0

    def test_stack_alone_still_works(self, monkeypatch):
        """Existing authored-stack path is unchanged."""
        calls: list = []
        monkeypatch.setattr(
            launcher, "_launch_host",
            lambda stack, harness, path, *, rm=False, extra=None: calls.append(stack),
        )
        result = runner.invoke(launcher.app, ["host-run", "hostspike"])
        assert result.exit_code == 0, result.output
        assert calls == ["hostspike"]


class TestHostRunRecipeMinting:
    """When --recipe is given: mint a generated stack, then call _launch_host. No _build_stack."""

    def test_recipes_mint_and_then_call_launch_host(self, monkeypatch, tmp_path):
        calls: dict[str, object] = {}
        monkeypatch.setattr(launcher.dynstack.paths, "generated_catalog_root", lambda: tmp_path)
        monkeypatch.setattr(
            launcher, "_launch_host",
            lambda stack, harness, path, *, rm=False, extra=None: calls.__setitem__(
                "launched", (stack, harness)
            ),
        )
        result = runner.invoke(
            launcher.app,
            ["host-run", "--recipe", "superpowers", "--recipe", "serena"],
        )
        assert result.exit_code == 0, result.output
        assert calls["launched"] == ("default.serena.superpowers", "claude")

    def test_recipe_defaults_to_extending_default(self, monkeypatch, tmp_path):
        monkeypatch.setattr(launcher.dynstack.paths, "generated_catalog_root", lambda: tmp_path)
        monkeypatch.setattr(launcher, "_launch_host", lambda *a, **k: None)
        runner.invoke(launcher.app, ["host-run", "--recipe", "serena"])
        text = (tmp_path / "stacks" / "default.serena" / "stack.yaml").read_text()
        assert "extends: default" in text

    def test_no_extends_drops_the_base(self, monkeypatch, tmp_path):
        monkeypatch.setattr(launcher.dynstack.paths, "generated_catalog_root", lambda: tmp_path)
        monkeypatch.setattr(launcher, "_launch_host", lambda *a, **k: None)
        runner.invoke(launcher.app, ["host-run", "--recipe", "serena", "--no-extends"])
        assert "extends:" not in (tmp_path / "stacks" / "serena" / "stack.yaml").read_text()

    def test_service_is_carried_into_the_minted_manifest(self, monkeypatch, tmp_path):
        monkeypatch.setattr(launcher.dynstack.paths, "generated_catalog_root", lambda: tmp_path)
        monkeypatch.setattr(launcher, "_launch_host", lambda *a, **k: None)
        runner.invoke(
            launcher.app,
            ["host-run", "--recipe", "serena", "--service", "beads-server"],
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
        result = runner.invoke(launcher.app, ["host-run", "--recipe", "serena"])
        assert result.exit_code == 0, result.output

    def test_services_identity_is_part_of_the_derived_name(self, monkeypatch, tmp_path):
        """Services are passed to BOTH derive_name and mint, so the name encodes the full identity."""
        monkeypatch.setattr(launcher.dynstack.paths, "generated_catalog_root", lambda: tmp_path)
        captured: dict = {}
        monkeypatch.setattr(
            launcher, "_launch_host",
            lambda stack, harness, path, *, rm=False, extra=None: captured.__setitem__("stack", stack),
        )

        runner.invoke(launcher.app, ["host-run", "--recipe", "serena"])
        name_without = captured.get("stack")
        runner.invoke(
            launcher.app,
            ["host-run", "--recipe", "serena", "--service", "beads-server"],
        )
        name_with = captured.get("stack")
        assert name_without != name_with, (
            "a different --service must produce a different stack name"
        )

    def test_a_project_path_can_be_given_alongside_recipes(self, monkeypatch, tmp_path):
        """`host-run --recipe serena ~/proj` is what a user naturally types. Typer binds that first
        positional to the `stack` slot, so without the shift it trips the XOR check and reports a
        stack the user never typed — the project path would be unreachable in the recipe form."""
        captured: dict = {}
        monkeypatch.setattr(launcher.dynstack.paths, "generated_catalog_root", lambda: tmp_path)
        monkeypatch.setattr(
            launcher, "_launch_host",
            lambda stack, harness, path, *, rm=False, extra=None: captured.update(
                stack=stack, path=path
            ),
        )
        result = runner.invoke(launcher.app, ["host-run", "--recipe", "serena", "/tmp/proj"])
        assert result.exit_code == 0, result.output
        assert captured == {"stack": "default.serena", "path": "/tmp/proj"}

    def test_the_shift_does_not_swallow_an_over_specified_invocation(self, monkeypatch, tmp_path):
        """The shift is guarded on `path` being empty. With both slots filled there is no coherent
        reading, so it must error rather than silently drop one."""
        monkeypatch.setattr(launcher.dynstack.paths, "generated_catalog_root", lambda: tmp_path)
        monkeypatch.setattr(launcher, "_launch_host", lambda *a, **k: None)
        result = runner.invoke(
            launcher.app, ["host-run", "--recipe", "serena", "some-stack", "/tmp/proj"]
        )
        assert result.exit_code != 0

    def test_mint_error_surfaces_as_nonzero_exit(self, monkeypatch, tmp_path):
        """An invalid recipe name that derive_name / mint rejects → clean error, not a traceback."""
        monkeypatch.setattr(launcher.dynstack.paths, "generated_catalog_root", lambda: tmp_path)
        monkeypatch.setattr(launcher, "_launch_host", lambda *a, **k: None)
        # A recipe name that sanitizes to the empty string (all unsafe chars) triggers ValueError.
        result = runner.invoke(launcher.app, ["host-run", "--recipe", "***"])
        assert result.exit_code != 0
