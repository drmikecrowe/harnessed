"""`harnessed run` — compose a stack from a recipe set at launch (harnessed-7rx.4)."""
from __future__ import annotations

import pytest
from typer.testing import CliRunner

from harnessed import launcher

runner = CliRunner()


def test_run_is_registered_and_routable():
    """Absent from _COMMANDS, main() routes `run` to `launch` and it fails confusingly."""
    assert "run" in launcher._COMMANDS


def test_run_mints_builds_then_launches(monkeypatch, tmp_path):
    calls: dict[str, object] = {}

    monkeypatch.setattr(launcher.dynstack.paths, "generated_catalog_root", lambda: tmp_path)
    monkeypatch.setattr(launcher, "_runtime", lambda: "podman")
    monkeypatch.setattr(
        launcher, "_build_stack",
        lambda rt, stack, harness, root=None, **kw: calls.__setitem__("built", (stack, harness)),
    )
    monkeypatch.setattr(
        launcher, "launch",
        lambda **kw: calls.__setitem__("launched", (kw["stack"], kw["harness"])),
    )

    result = runner.invoke(
        launcher.app, ["run", "--recipe", "superpowers", "--recipe", "serena", "claude"]
    )
    assert result.exit_code == 0, result.output
    assert calls["built"] == ("default+serena+superpowers", "claude")
    assert calls["launched"] == ("default+serena+superpowers", "claude")


def test_run_defaults_to_extending_default(monkeypatch, tmp_path):
    monkeypatch.setattr(launcher.dynstack.paths, "generated_catalog_root", lambda: tmp_path)
    monkeypatch.setattr(launcher, "_runtime", lambda: "podman")
    monkeypatch.setattr(launcher, "_build_stack", lambda *a, **k: None)
    monkeypatch.setattr(launcher, "launch", lambda **kw: None)

    runner.invoke(launcher.app, ["run", "--recipe", "serena", "claude"])
    text = (tmp_path / "stacks" / "default+serena" / "stack.yaml").read_text()
    assert "extends: default" in text


def test_no_extends_drops_the_base(monkeypatch, tmp_path):
    monkeypatch.setattr(launcher.dynstack.paths, "generated_catalog_root", lambda: tmp_path)
    monkeypatch.setattr(launcher, "_runtime", lambda: "podman")
    monkeypatch.setattr(launcher, "_build_stack", lambda *a, **k: None)
    monkeypatch.setattr(launcher, "launch", lambda **kw: None)

    runner.invoke(launcher.app, ["run", "--recipe", "serena", "--no-extends", "claude"])
    assert "extends:" not in (tmp_path / "stacks" / "serena" / "stack.yaml").read_text()


def test_run_requires_at_least_one_recipe(monkeypatch, tmp_path):
    monkeypatch.setattr(launcher.dynstack.paths, "generated_catalog_root", lambda: tmp_path)
    result = runner.invoke(launcher.app, ["run", "claude"])
    assert result.exit_code != 0
    # NOTE: `_err` writes to stderr via rich. Depending on the CliRunner's stderr handling the text
    # may not land in `result.output`, so the EXIT CODE is the contract here. If you want to assert
    # the wording, capture stderr explicitly with `CliRunner(mix_stderr=False)` and read
    # `result.stderr` — do not weaken this to `exit_code == 0`.


def test_unknown_harness_is_rejected(monkeypatch, tmp_path):
    monkeypatch.setattr(launcher.dynstack.paths, "generated_catalog_root", lambda: tmp_path)
    result = runner.invoke(launcher.app, ["run", "--recipe", "serena", "not-a-harness"])
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
    monkeypatch.setattr(launcher, "launch", lambda **kw: None)

    runner.invoke(launcher.app, ["run", "--recipe", "serena", "claude"])
    assert not (tmp_path / "stacks" / "default+serena").exists()


def test_failed_build_keeps_a_preexisting_manifest(monkeypatch, tmp_path):
    """Deleting someone's already-working stack because today's build broke is collateral damage."""
    monkeypatch.setattr(launcher.dynstack.paths, "generated_catalog_root", lambda: tmp_path)
    monkeypatch.setattr(launcher, "_runtime", lambda: "podman")
    monkeypatch.setattr(launcher, "launch", lambda **kw: None)
    monkeypatch.setattr(launcher, "_build_stack", lambda *_a, **_kw: None)
    runner.invoke(launcher.app, ["run", "--recipe", "serena", "claude"])  # first run: creates it

    def boom(*_a, **_kw):
        raise RuntimeError("build failed")

    monkeypatch.setattr(launcher, "_build_stack", boom)
    runner.invoke(launcher.app, ["run", "--recipe", "serena", "claude"])
    assert (tmp_path / "stacks" / "default+serena" / "stack.yaml").is_file()
