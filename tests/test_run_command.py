"""`harnessed container-run --recipe` — compose a stack from a recipe set at launch (harnessed-7rx.4).

This was `harnessed run`, a separate verb that minted a stack and then called `launch`. The two
collapsed into one verb whose `--stack` / `--recipe` options pick the stack SOURCE while the verb
picks the backend, so the seam these tests cover is now the top of `container_run` rather than a
delegation between two commands.

Because there is no delegation left to stub, these drive the real `container-run` and cut it short
just past the mint-and-build seam by pointing it at a project directory that does not exist — the
first check after the build, and deliberately NOT an exception from inside the build itself, which
`container_run` catches to clean up a manifest it just minted. Everything past that point is the
container launch proper, which needs a live podman and is covered elsewhere.
"""
from __future__ import annotations

from typer.testing import CliRunner

from harnessed import launcher

runner = CliRunner()


def _stub_build(monkeypatch, calls: dict):
    """Let the build 'succeed', recording its arguments. Stops nothing by itself."""
    monkeypatch.setattr(launcher, "_runtime", lambda: "podman")
    monkeypatch.setattr(
        launcher, "_build_stack",
        lambda _rt, stack, harness, *_a, **_kw: calls.__setitem__("built", (stack, harness)),
    )


def _nowhere(tmp_path) -> str:
    """A path that fails `is_dir()` — the cut point just after the build."""
    return str(tmp_path / "no-such-project")


def test_recipes_mint_then_build(monkeypatch, tmp_path):
    calls: dict[str, object] = {}
    monkeypatch.setattr(launcher.dynstack.paths, "generated_catalog_root", lambda: tmp_path)
    _stub_build(monkeypatch, calls)

    runner.invoke(
        launcher.app,
        ["container-run", "claude", _nowhere(tmp_path),
         "--recipe", "superpowers", "--recipe", "serena"],
    )
    assert calls["built"] == ("default.serena.superpowers", "claude")


def test_defaults_to_extending_default(monkeypatch, tmp_path):
    monkeypatch.setattr(launcher.dynstack.paths, "generated_catalog_root", lambda: tmp_path)
    _stub_build(monkeypatch, {})

    runner.invoke(
        launcher.app, ["container-run", "claude", _nowhere(tmp_path), "--recipe", "serena"]
    )
    text = (tmp_path / "stacks" / "default.serena" / "stack.yaml").read_text()
    assert "extends: default" in text


def test_no_extends_drops_the_base(monkeypatch, tmp_path):
    monkeypatch.setattr(launcher.dynstack.paths, "generated_catalog_root", lambda: tmp_path)
    _stub_build(monkeypatch, {})

    runner.invoke(
        launcher.app,
        ["container-run", "claude", _nowhere(tmp_path), "--recipe", "serena", "--no-extends"],
    )
    assert "extends:" not in (tmp_path / "stacks" / "serena" / "stack.yaml").read_text()


def test_requires_a_stack_or_a_recipe(monkeypatch, tmp_path):
    monkeypatch.setattr(launcher.dynstack.paths, "generated_catalog_root", lambda: tmp_path)
    result = runner.invoke(launcher.app, ["container-run", "claude"])
    assert result.exit_code != 0
    # NOTE: `_err` writes to stderr via rich. Depending on the CliRunner's stderr handling the text
    # may not land in `result.output`, so the EXIT CODE is the contract here. If you want to assert
    # the wording, capture stderr explicitly with `CliRunner(mix_stderr=False)` and read
    # `result.stderr` — do not weaken this to `exit_code == 0`.


def test_stack_and_recipe_are_mutually_exclusive(monkeypatch, tmp_path):
    """Same rule as host-run, from the same `_resolve_stack` — the verbs must not drift."""
    monkeypatch.setattr(launcher.dynstack.paths, "generated_catalog_root", lambda: tmp_path)
    result = runner.invoke(
        launcher.app, ["container-run", "claude", "--stack", "s", "--recipe", "serena"]
    )
    assert result.exit_code != 0
    assert not list(tmp_path.glob("stacks/*/stack.yaml")), "nothing may be minted either"


def test_an_authored_stack_is_not_built(monkeypatch, tmp_path):
    """`--stack` names something that already assembled; only the minted form needs a build."""
    monkeypatch.setattr(launcher.dynstack.paths, "generated_catalog_root", lambda: tmp_path)
    monkeypatch.setattr(launcher, "_runtime", lambda: "podman")

    def boom(*_a, **_kw):
        raise AssertionError("_build_stack must not run for an authored stack")

    monkeypatch.setattr(launcher, "_build_stack", boom)
    result = runner.invoke(
        launcher.app, ["container-run", "claude", _nowhere(tmp_path), "--stack", "hostspike"]
    )
    assert result.exit_code != 0, "expected the missing-project-dir exit, not a build"


def test_unknown_harness_is_rejected(monkeypatch, tmp_path):
    monkeypatch.setattr(launcher.dynstack.paths, "generated_catalog_root", lambda: tmp_path)
    result = runner.invoke(launcher.app, ["container-run", "not-a-harness", "--recipe", "serena"])
    assert result.exit_code != 0


def test_failed_build_removes_a_manifest_this_run_created(monkeypatch, tmp_path):
    """A stack that never built owns no volumes, so no GC would ever reclaim it — it would just
    sit in `harnessed list` forever. (`dynstack` does `from . import paths`, so patching
    `dynstack.paths` patches the one shared module object that launcher sees too.)"""
    monkeypatch.setattr(launcher.dynstack.paths, "generated_catalog_root", lambda: tmp_path)
    monkeypatch.setattr(launcher, "_runtime", lambda: "podman")

    def boom(*_a, **_kw):
        raise RuntimeError("build failed")

    monkeypatch.setattr(launcher, "_build_stack", boom)

    runner.invoke(launcher.app, ["container-run", "claude", "--recipe", "serena"])
    assert not (tmp_path / "stacks" / "default.serena").exists()


def test_failed_build_keeps_a_preexisting_manifest(monkeypatch, tmp_path):
    """Deleting someone's already-working stack because today's build broke is collateral damage."""
    monkeypatch.setattr(launcher.dynstack.paths, "generated_catalog_root", lambda: tmp_path)
    _stub_build(monkeypatch, {})
    runner.invoke(  # first run: mints it and survives the build
        launcher.app, ["container-run", "claude", _nowhere(tmp_path), "--recipe", "serena"]
    )
    assert (tmp_path / "stacks" / "default.serena" / "stack.yaml").is_file(), "setup failed"

    def boom(*_a, **_kw):
        raise RuntimeError("build failed")

    monkeypatch.setattr(launcher, "_build_stack", boom)
    runner.invoke(launcher.app, ["container-run", "claude", "--recipe", "serena"])
    assert (tmp_path / "stacks" / "default.serena" / "stack.yaml").is_file()
