"""`harnessed host-run` — accept a recipe set (--recipe) without authoring a stack.yaml (harnessed-cta)."""
from __future__ import annotations

import pytest
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
        result = runner.invoke(launcher.app, ["host-run", "my-stack", "--recipe", "serena"])
        assert result.exit_code != 0
        assert "not both" in result.output
        assert launched == [], "nothing may be launched when the invocation is rejected"
        assert not list(tmp_path.glob("stacks/*/stack.yaml")), "nothing may be minted either"

    def test_neither_stack_nor_recipe_is_an_error(self):
        result = runner.invoke(launcher.app, ["host-run"])
        assert result.exit_code != 0
        assert "at least one --recipe" in result.output

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

    def test_a_project_path_is_given_with_the_path_option(self, monkeypatch, tmp_path):
        """`--path` exists because positionals are ambiguous here: Typer binds by declaration order,
        so under --recipe a lone `~/proj` and a stack name are the same token."""
        captured: dict = {}
        monkeypatch.setattr(launcher.dynstack.paths, "generated_catalog_root", lambda: tmp_path)
        monkeypatch.setattr(
            launcher, "_launch_host",
            lambda stack, harness, path, *, rm=False, extra=None: captured.update(
                stack=stack, path=path
            ),
        )
        proj = tmp_path / "proj"
        result = runner.invoke(
            launcher.app, ["host-run", "--recipe", "serena", "--path", str(proj)]
        )
        assert result.exit_code == 0, result.output
        assert captured == {"stack": "default.serena", "path": str(proj)}

    @pytest.mark.parametrize("extra", [
        ["some/project/dir"],       # meant as a path — indistinguishable from a stack name
        ["claude"],                 # a VALID harness: the case the old shift silently swallowed
        ["some-stack", "claude"],
        ["some-stack", "claude", "some/project/dir"],
    ])
    def test_positionals_are_rejected_with_recipes(self, monkeypatch, tmp_path, extra):
        """Every positional shape must be refused rather than reinterpreted. The `claude` case is
        the one that matters most: the previous shift fired whenever `path` was empty, so it demoted
        `some-stack` to a project path and exited 0."""
        launched: list = []
        monkeypatch.setattr(launcher.dynstack.paths, "generated_catalog_root", lambda: tmp_path)
        monkeypatch.setattr(launcher, "_launch_host", lambda *a, **k: launched.append(a))
        result = runner.invoke(launcher.app, ["host-run", "--recipe", "serena", *extra])
        assert result.exit_code != 0, result.output
        assert launched == [], "an ambiguous invocation must not launch anything"

    def test_a_stack_positional_before_recipe_flags_still_trips_exclusivity(
        self, monkeypatch, tmp_path
    ):
        """Regression for the exact bypass CodeRabbit caught: `host-run <stack> --recipe X` exited 0
        and launched the GENERATED stack, with the authored name demoted to a project path."""
        launched: list = []
        monkeypatch.setattr(launcher.dynstack.paths, "generated_catalog_root", lambda: tmp_path)
        monkeypatch.setattr(launcher, "_launch_host", lambda *a, **k: launched.append(a))
        result = runner.invoke(
            launcher.app, ["host-run", "my-authored-stack", "--recipe", "serena"]
        )
        assert result.exit_code != 0
        assert launched == []

    def test_path_option_and_positional_path_together_is_an_error(self, monkeypatch):
        """Authored form accepts both spellings; giving the directory twice has no sane reading."""
        monkeypatch.setattr(launcher, "_launch_host", lambda *a, **k: None)
        result = runner.invoke(
            launcher.app,
            ["host-run", "my-stack", "claude", "positional-dir", "--path", "option-dir"],
        )
        assert result.exit_code != 0
        assert "once, not twice" in result.output

    def test_mint_error_surfaces_as_nonzero_exit(self, monkeypatch, tmp_path):
        """An invalid recipe name that derive_name / mint rejects → clean error, not a traceback."""
        monkeypatch.setattr(launcher.dynstack.paths, "generated_catalog_root", lambda: tmp_path)
        monkeypatch.setattr(launcher, "_launch_host", lambda *a, **k: None)
        # A recipe name that sanitizes to the empty string (all unsafe chars) triggers ValueError.
        result = runner.invoke(launcher.app, ["host-run", "--recipe", "***"])
        assert result.exit_code != 0
